"""Typed extraction of coral branch candidates from explicitly verified masks."""

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import ImageAsset, MaskAnnotation, WorkflowArtifact
from reefvision.domain.errors import ValidationError
from reefvision.schemas.skeletonization import SkeletonAnalysisCreateRequest
from reefvision.schemas.workflow_graphs import (
    WorkflowNodeDefinitionResponse,
    WorkflowPortDefinition,
)
from reefvision.services.connected_branch_preview import source_skeleton_graph
from reefvision.services.skeletonization import (
    SkeletonizationService,
    skeleton_calibration_payload,
    skeleton_edge_physical_lengths,
)


def coral_skeleton_node() -> WorkflowNodeDefinitionResponse:
    return WorkflowNodeDefinitionResponse(
        node_type="ecology_coral_skeleton",
        display_name="Extract Coral Branch Candidates",
        category="Scientific analysis",
        description="Measure deterministic segment candidates from one verified colony mask.",
        input_ports=[
            WorkflowPortDefinition(
                port_id="mask",
                display_name="Verified mask",
                accepted_types=["mask_annotations", "reviewed_masks"],
            ),
        ],
        output_ports=[
            WorkflowPortDefinition(
                port_id="skeleton",
                display_name="Coral branch candidate",
                accepted_types=["coral_skeleton_candidate"],
                multiple=True,
            )
        ],
        required_parameters=[],
        optional_parameters={"terminal_spur_max_length_pixels": 0},
        execution_state="executable",
        executable=True,
        implementation_notes=[
            "Use one mask from Verified Masks or Mask Review.",
            "Publishes an unreviewed skeleton for explicit review in the mask editor.",
        ],
    )


def execute_coral_skeleton(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    if set(parameters) - {
        "terminal_spur_max_length_pixels",
        "__workflow_run_id",
        "__workflow_node_run_id",
    }:
        raise ValidationError("Coral branch extraction has unsupported parameters")
    threshold = parameters.get("terminal_spur_max_length_pixels", 0)
    if type(threshold) not in (int, float) or not 0 <= threshold <= 10000:
        raise ValidationError("Spur threshold must be a number between 0 and 10,000 pixels")
    sources = inputs.get("mask", [])
    if len(sources) != 1 or sources[0].payload_json.get("project_id") != project_id:
        raise ValidationError("Coral branch extraction requires a project-owned verified mask")
    identifiers = sources[0].payload_json.get("mask_annotation_ids")
    if not isinstance(identifiers, list) or len(identifiers) != 1:
        raise ValidationError("Select exactly one verified colony mask for each extraction")
    try:
        mask_id = str(UUID(identifiers[0]))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError("Colony mask identifier is invalid") from exc
    mask = session.get(MaskAnnotation, mask_id)
    image = session.get(ImageAsset, mask.image_id) if mask else None
    if (
        mask is None
        or mask.deleted_at is not None
        or mask.status != "verified"
        or image is None
        or image.project_id != project_id
    ):
        raise ValidationError("Colony mask is missing, unverified, or owned by another project")
    service = SkeletonizationService(session, settings)
    request = (
        SkeletonAnalysisCreateRequest(terminal_spur_max_length_pixels=threshold)
        if threshold
        else SkeletonAnalysisCreateRequest()
    )
    result = service.persist_analysis(
        mask_id,
        request,
    )
    nodes, edges = source_skeleton_graph(result, image)
    calibration = skeleton_calibration_payload(image)
    physical = skeleton_edge_physical_lengths(
        nodes,
        edges,
        calibration,
        reject_projective_horizon=True,
    )
    return [
        {
            "port_id": "skeleton",
            "data_type": "coral_skeleton_candidate",
            "payload": {
                "project_id": project_id,
                "analysis_id": result.id,
                "mask_annotation_id": result.mask_annotation_id,
                "image_id": result.image_id,
                "analysis_sha256": result.result_sha256,
                "mask_sha256": result.input_mask_sha256,
                "mask_revision": result.mask_revision,
                "calibration_sha256": result.calibration_sha256,
                "algorithm": result.algorithm,
                "algorithm_version": result.algorithm_version,
                "parameters_sha256": result.parameters_sha256,
                "terminal_spur_max_length_pixels": result.terminal_spur_max_length_pixels,
                "physical_unit": calibration.unit if calibration else None,
                "geometry_space": "source_image_pixels_2d",
                "length_calibration_method": result.result.length_calibration_method,
                "evidence_level": "proposal_unverified",
                "review_gate": "scientist_review_required",
                "quality_control": {
                    "mask_foreground_pixels": result.result.input_foreground_pixels,
                    "skeleton_pixels": len(result.result.final_skeleton_pixels),
                    "removed_spurs": result.result.removed_spur_count,
                },
                "total_length_pixels": sum(edge.node_to_node_length_pixels for edge in edges),
                "total_length_physical": sum(physical.values()) if calibration else None,
                "nodes": [
                    {"id": node.id, "kind": node.kind, "x": node.x, "y": node.y} for node in nodes
                ],
                "edges": [
                    {
                        "candidate_id": edge.id,
                        "source_node_id": edge.source_node_id,
                        "target_node_id": edge.target_node_id,
                        "length_pixels": edge.node_to_node_length_pixels,
                        "length_physical": physical.get(edge.id),
                        "points": [{"x": x, "y": y} for x, y in edge.pixels],
                    }
                    for edge in edges
                ],
            },
        }
    ]
