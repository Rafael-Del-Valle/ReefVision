"""Read-only branch preview backed by a current saved skeleton analysis."""

from __future__ import annotations

from math import isclose

from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import ImageAsset
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.connected_branch_editing import (
    ConnectedBranchEdgeResponse,
    ConnectedBranchNodeResponse,
    ConnectedBranchPreviewRequest,
    ConnectedBranchPreviewResponse,
)
from reefvision.schemas.skeletonization import SkeletonPixelEdit
from reefvision.services.connected_branch_editing import (
    BranchEditError,
    preview_connected_branch_addition,
)
from reefvision.services.skeleton_algorithms import (
    build_initial_branch_graph,
    classify_skeleton_pixels,
    consolidate_junction_clusters,
)
from reefvision.services.skeletonization import SkeletonizationService
from reefvision.storage.datasets import canonical_json_sha256


def _point(x: int, y: int) -> SkeletonPixelEdit:
    return SkeletonPixelEdit(x=x, y=y)


def preview_saved_branch_addition(
    session: Session,
    settings: Settings,
    analysis_id: str,
    payload: ConnectedBranchPreviewRequest,
) -> ConnectedBranchPreviewResponse:
    """Return an unverified graph proposal; never alter the approved revision."""
    source = SkeletonizationService(session, settings).get_persisted_analysis(analysis_id)
    if source.stale or not source.is_latest_revision:
        raise ValidationError("Branch edits must use the latest non-stale skeleton analysis")
    if canonical_json_sha256(source.result.model_dump(mode="json")) != source.result_sha256:
        raise ValidationError("Persisted skeleton analysis result checksum does not match")

    image = session.get(ImageAsset, source.image_id)
    if image is None:
        raise NotFoundError("Source image no longer exists")
    if any(point.x >= image.width_px or point.y >= image.height_px for point in payload.points):
        raise ValidationError("Proposed branch extends outside the source image")

    pixels = source.result.final_skeleton_pixels
    if not pixels:
        raise ValidationError("Saved analysis has no final skeleton pixels")
    data = bytearray(image.width_px * image.height_px)
    for pixel in pixels:
        if pixel.x >= image.width_px or pixel.y >= image.height_px:
            raise ValidationError("Persisted skeleton coordinate is outside the source image")
        data[pixel.y * image.width_px + pixel.x] = 255
    mask = (bytes(data), image.width_px, image.height_px)
    features = classify_skeleton_pixels(mask)
    clusters = consolidate_junction_clusters(features)
    nodes, edges = build_initial_branch_graph(features, clusters)

    stored_edges = source.result.final_graph_edges
    if len(stored_edges) != len(edges) or len(source.result.final_graph_nodes) != len(nodes):
        raise ValidationError("Saved graph topology is inconsistent with its skeleton pixels")
    for recorded, derived in zip(stored_edges, edges, strict=True):
        if (
            recorded.id != derived.id
            or recorded.source_node_id != derived.source_node_id
            or recorded.target_node_id != derived.target_node_id
            or not isclose(
                recorded.node_to_node_length_pixels,
                derived.node_to_node_length_pixels,
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
        ):
            raise ValidationError("Saved graph differs from source skeleton geometry")
    try:
        proposal = preview_connected_branch_addition(
            nodes,
            edges,
            [(point.x, point.y) for point in payload.points],
            edit_id=payload.edit_id,
        )
    except BranchEditError as exc:
        raise ValidationError(str(exc)) from exc

    return ConnectedBranchPreviewResponse(
        base_analysis_id=source.id,
        base_result_sha256=source.result_sha256,
        image_id=source.image_id,
        mask_annotation_id=source.mask_annotation_id,
        attached_node_id=proposal.attached_node_id,
        added_edge_id=proposal.added_edge_id,
        superseded_edge_ids=list(proposal.superseded_edge_ids),
        replacement_edge_ids=list(proposal.replacement_edge_ids),
        original_total_length_pixels=proposal.original_total_length_pixels,
        proposed_total_length_pixels=proposal.proposed_total_length_pixels,
        added_length_pixels=proposal.added_length_pixels,
        nodes=[
            ConnectedBranchNodeResponse(
                id=node.id,
                kind=node.kind,
                x=node.x,
                y=node.y,
                source_pixels=[_point(x, y) for x, y in node.source_pixels],
                external_connection_count=node.external_connection_count,
            )
            for node in proposal.nodes
        ],
        edges=[
            ConnectedBranchEdgeResponse(
                id=edge.id,
                source_node_id=edge.source_node_id,
                target_node_id=edge.target_node_id,
                pixels=[_point(x, y) for x, y in edge.pixels],
                boundary_to_boundary_length_pixels=edge.boundary_to_boundary_length_pixels,
                node_to_node_length_pixels=edge.node_to_node_length_pixels,
                is_cycle=edge.is_cycle,
            )
            for edge in proposal.edges
        ],
    )
