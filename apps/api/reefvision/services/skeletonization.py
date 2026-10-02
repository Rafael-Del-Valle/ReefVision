"""Conservative coral skeletonization readiness and raw analysis."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from hashlib import sha256
from heapq import heappop, heappush
from itertools import pairwise
from math import acos, degrees, hypot
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageDraw, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    ImageAsset,
    MaskAnnotation,
    Project,
    SkeletonAnalysisRevision,
)
from reefvision.db.models.project import utc_now
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.repositories.mask_annotations import MaskAnnotationRepository
from reefvision.schemas.measurements import MeasurementCalibrationUpdate
from reefvision.schemas.skeletonization import (
    SkeletonAnalysisCorrectionRequest,
    SkeletonAnalysisCreateRequest,
    SkeletonAnalysisExportResponse,
    SkeletonAnalysisReviewRequest,
    SkeletonAnalysisRevisionResponse,
    SkeletonBranchAngleResponse,
    SkeletonFeaturePixelResponse,
    SkeletonGraphEdgeResponse,
    SkeletonGraphNodeResponse,
    SkeletonizationAnalysisResponse,
    SkeletonizationReadinessResponse,
    SkeletonJunctionClusterResponse,
    SkeletonMaskComponentResponse,
    SkeletonPixelCoordinateResponse,
    SkeletonResolutionAction,
    SkeletonSpurRemovalResponse,
)
from reefvision.services.calibration_geometry import transform_point
from reefvision.services.skeleton_algorithms import (
    BinaryMask,
    SkeletonGraphEdge,
    SkeletonGraphNode,
    branch_angles,
    build_initial_branch_graph,
    classify_skeleton_pixels,
    consolidate_junction_clusters,
    graph_diameter_pixels,
    prune_terminal_spurs,
    total_graph_length_pixels,
    zhang_suen_thin,
)
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.storage.skeleton_exports import (
    build_skeleton_export,
    skeleton_export_stem,
)


@dataclass(frozen=True, slots=True)
class _Component:
    pixel_count: int
    x_min: int
    y_min: int
    x_max: int
    y_max: int
    touches_image_border: bool


_NEIGHBORS_8 = (
    (-1, -1),
    (0, -1),
    (1, -1),
    (-1, 0),
    (1, 0),
    (-1, 1),
    (0, 1),
    (1, 1),
)


MEASUREMENT_CALIBRATION_KEY = "measurement_calibration"


def _pixel_coordinates(mask: BinaryMask) -> list[SkeletonPixelCoordinateResponse]:
    data, width, height = mask
    return [
        SkeletonPixelCoordinateResponse(x=x, y=y)
        for y in range(height)
        for x in range(width)
        if data[y * width + x] > 0
    ]


def _binary_mask_sha256(mask: BinaryMask) -> str:
    data, width, height = mask
    digest = sha256()
    digest.update(width.to_bytes(8, "little", signed=False))
    digest.update(height.to_bytes(8, "little", signed=False))
    digest.update(data)
    return digest.hexdigest()


def _calibration_sha256(image: ImageAsset) -> str | None:
    raw = dict(image.metadata_json or {}).get(MEASUREMENT_CALIBRATION_KEY)
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValidationError("Image measurement calibration metadata is invalid")
    return canonical_json_sha256(raw)


def _analysis_parameters_sha256(
    terminal_spur_max_length_pixels: float,
) -> str:
    return canonical_json_sha256(
        {
            "schema_version": "skeleton-analysis-parameters-0001",
            "algorithm": "zhang_suen",
            "algorithm_version": "0001",
            "connectivity": 8,
            "pre_thinning_cleanup": "binary_normalization_only",
            "automatic_bridge_applied": False,
            "terminal_spur_max_length_pixels": terminal_spur_max_length_pixels,
        }
    )


def _calibration_payload(image: ImageAsset) -> MeasurementCalibrationUpdate | None:
    raw = dict(image.metadata_json or {}).get(MEASUREMENT_CALIBRATION_KEY)
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValidationError("Image measurement calibration metadata is invalid")
    try:
        return MeasurementCalibrationUpdate.model_validate(raw)
    except ValueError as exc:
        raise ValidationError("Image measurement calibration metadata is invalid") from exc


def _edge_polyline(
    edge: SkeletonGraphEdge,
    node_by_id: dict[str, SkeletonGraphNode],
) -> list[tuple[float, float]]:
    source = node_by_id[edge.source_node_id]
    target = node_by_id[edge.target_node_id]
    points: list[tuple[float, float]] = [(source.x, source.y)]
    points.extend((float(x), float(y)) for x, y in edge.pixels)
    points.append((target.x, target.y))

    deduplicated: list[tuple[float, float]] = []
    for point in points:
        if deduplicated and point == deduplicated[-1]:
            continue
        deduplicated.append(point)
    return deduplicated


def _edge_physical_lengths(
    nodes: list[SkeletonGraphNode] | tuple[SkeletonGraphNode, ...],
    edges: list[SkeletonGraphEdge] | tuple[SkeletonGraphEdge, ...],
    calibration: MeasurementCalibrationUpdate | None,
) -> dict[str, float]:
    if calibration is None:
        return {}

    if calibration.perspective_homography is None:
        return {
            edge.id: edge.node_to_node_length_pixels * calibration.distance_per_pixel
            for edge in edges
        }

    node_by_id = {node.id: node for node in nodes}
    physical: dict[str, float] = {}
    for edge in edges:
        transformed = [
            transform_point(calibration.perspective_homography, point)
            for point in _edge_polyline(edge, node_by_id)
        ]
        physical[edge.id] = sum(
            hypot(second[0] - first[0], second[1] - first[1])
            for first, second in pairwise(transformed)
        )
    return physical


def _weighted_graph_diameter(
    nodes: list[SkeletonGraphNode] | tuple[SkeletonGraphNode, ...],
    edges: list[SkeletonGraphEdge] | tuple[SkeletonGraphEdge, ...],
    weights: dict[str, float],
) -> float:
    if not nodes or not edges:
        return 0.0

    adjacency: dict[str, list[tuple[str, float]]] = {node.id: [] for node in nodes}
    cycle_diameter = 0.0
    for edge in edges:
        weight = weights[edge.id]
        if edge.source_node_id == edge.target_node_id:
            cycle_diameter = max(cycle_diameter, weight / 2.0)
            continue
        adjacency[edge.source_node_id].append((edge.target_node_id, weight))
        adjacency[edge.target_node_id].append((edge.source_node_id, weight))

    maximum = cycle_diameter
    for source in adjacency:
        distances = {source: 0.0}
        queue: list[tuple[float, str]] = [(0.0, source)]
        while queue:
            distance, current = heappop(queue)
            if distance != distances.get(current):
                continue
            maximum = max(maximum, distance)
            for neighbor, weight in adjacency[current]:
                candidate = distance + weight
                if candidate < distances.get(neighbor, float("inf")):
                    distances[neighbor] = candidate
                    heappush(queue, (candidate, neighbor))
    return maximum


def _reference_plane_branch_angles(
    nodes: list[SkeletonGraphNode] | tuple[SkeletonGraphNode, ...],
    edges: list[SkeletonGraphEdge] | tuple[SkeletonGraphEdge, ...],
    matrix: list[list[float]],
) -> list[SkeletonBranchAngleResponse]:
    node_by_id = {node.id: node for node in nodes}
    incident: dict[str, list[tuple[SkeletonGraphEdge, tuple[float, float]]]] = {}

    for edge in edges:
        source = node_by_id[edge.source_node_id]
        target = node_by_id[edge.target_node_id]
        if source.kind == "junction" and len(edge.pixels) >= 2:
            incident.setdefault(source.id, []).append(
                (edge, (float(edge.pixels[1][0]), float(edge.pixels[1][1])))
            )
        if target.kind == "junction" and len(edge.pixels) >= 2:
            incident.setdefault(target.id, []).append(
                (edge, (float(edge.pixels[-2][0]), float(edge.pixels[-2][1])))
            )

    results: list[SkeletonBranchAngleResponse] = []
    for junction_id, branches in sorted(incident.items()):
        junction = node_by_id[junction_id]
        origin = transform_point(matrix, (junction.x, junction.y))
        ordered = sorted(branches, key=lambda item: item[0].id)
        for first_index in range(len(ordered)):
            first_edge, first_point = ordered[first_index]
            first_target = transform_point(matrix, first_point)
            first_vector = (
                first_target[0] - origin[0],
                first_target[1] - origin[1],
            )
            first_norm = hypot(*first_vector)
            if first_norm == 0:
                continue
            for second_edge, second_point in ordered[first_index + 1 :]:
                second_target = transform_point(matrix, second_point)
                second_vector = (
                    second_target[0] - origin[0],
                    second_target[1] - origin[1],
                )
                second_norm = hypot(*second_vector)
                if second_norm == 0:
                    continue
                cosine = (
                    first_vector[0] * second_vector[0]
                    + first_vector[1] * second_vector[1]
                ) / (first_norm * second_norm)
                cosine = max(-1.0, min(1.0, cosine))
                results.append(
                    SkeletonBranchAngleResponse(
                        junction_id=junction_id,
                        first_branch_id=first_edge.id,
                        second_branch_id=second_edge.id,
                        angle_degrees=degrees(acos(cosine)),
                    )
                )
    return results


def _branch_angle_responses(
    nodes: list[SkeletonGraphNode] | tuple[SkeletonGraphNode, ...],
    edges: list[SkeletonGraphEdge] | tuple[SkeletonGraphEdge, ...],
    calibration: MeasurementCalibrationUpdate | None,
) -> list[SkeletonBranchAngleResponse]:
    if calibration is not None and calibration.perspective_homography is not None:
        return _reference_plane_branch_angles(
            nodes,
            edges,
            calibration.perspective_homography,
        )
    return [
        SkeletonBranchAngleResponse(
            junction_id=angle.junction_id,
            first_branch_id=angle.first_branch_id,
            second_branch_id=angle.second_branch_id,
            angle_degrees=angle.angle_degrees,
        )
        for angle in branch_angles(nodes, edges)
    ]


def _binary_mask_from_image(path: Path, *, width: int, height: int) -> BinaryMask:
    try:
        with Image.open(path) as image:
            image.load()
            if image.size != (width, height):
                raise ValidationError(
                    "Raster mask dimensions do not match the source image"
                )
            binary = image.convert("L").point(lambda value: 255 if value > 0 else 0)
            return binary.tobytes(), width, height
    except (OSError, UnidentifiedImageError) as exc:
        raise ValidationError("Raster mask content could not be read") from exc


def _binary_mask_from_polygon(
    points: list[list[float]],
    *,
    width: int,
    height: int,
) -> BinaryMask:
    if len(points) < 3:
        raise ValidationError("Polygon mask does not have valid geometry")
    image = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(image)
    draw.polygon(
        [(float(point[0]), float(point[1])) for point in points],
        fill=255,
    )
    return image.tobytes(), width, height


def _connected_components_8(mask: BinaryMask) -> list[_Component]:
    data, width, height = mask
    visited = bytearray(width * height)
    components: list[_Component] = []

    for y in range(height):
        for x in range(width):
            start = y * width + x
            if visited[start] or data[start] == 0:
                continue

            queue: deque[tuple[int, int]] = deque([(x, y)])
            visited[start] = 1
            count = 0
            x_min = x_max = x
            y_min = y_max = y
            touches_border = False

            while queue:
                current_x, current_y = queue.popleft()
                count += 1
                x_min = min(x_min, current_x)
                y_min = min(y_min, current_y)
                x_max = max(x_max, current_x)
                y_max = max(y_max, current_y)
                touches_border = touches_border or (
                    current_x == 0
                    or current_y == 0
                    or current_x == width - 1
                    or current_y == height - 1
                )

                for dx, dy in _NEIGHBORS_8:
                    nx = current_x + dx
                    ny = current_y + dy
                    if nx < 0 or ny < 0 or nx >= width or ny >= height:
                        continue
                    offset = ny * width + nx
                    if visited[offset] or data[offset] == 0:
                        continue
                    visited[offset] = 1
                    queue.append((nx, ny))

            components.append(
                _Component(
                    pixel_count=count,
                    x_min=x_min,
                    y_min=y_min,
                    x_max=x_max,
                    y_max=y_max,
                    touches_image_border=touches_border,
                )
            )

    components.sort(
        key=lambda item: (
            -item.pixel_count,
            item.y_min,
            item.x_min,
            item.y_max,
            item.x_max,
        )
    )
    return components


class SkeletonizationService:
    """Validate masks and derive topology-preserving raw skeletons."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.masks = MaskAnnotationRepository(session)

    def _mask(self, mask_annotation_id: str) -> MaskAnnotation:
        mask = self.masks.get(mask_annotation_id)
        if mask is None or mask.deleted_at is not None:
            raise NotFoundError("Mask annotation not found")
        return mask

    def _image(self, image_id: str) -> ImageAsset:
        image = self.session.get(ImageAsset, image_id)
        if image is None:
            raise NotFoundError("Image not found")
        return image

    @staticmethod
    def _edge_responses(
        nodes: list[SkeletonGraphNode] | tuple[SkeletonGraphNode, ...],
        edges: list[SkeletonGraphEdge] | tuple[SkeletonGraphEdge, ...],
        physical_lengths: dict[str, float],
    ) -> list[SkeletonGraphEdgeResponse]:
        return [
            SkeletonGraphEdgeResponse(
                id=edge.id,
                source_node_id=edge.source_node_id,
                target_node_id=edge.target_node_id,
                path_pixel_count=len(edge.pixels),
                boundary_to_boundary_length_pixels=(
                    edge.boundary_to_boundary_length_pixels
                ),
                node_to_node_length_pixels=edge.node_to_node_length_pixels,
                length_physical=physical_lengths.get(edge.id),
                is_cycle=edge.is_cycle,
            )
            for edge in edges
        ]

    def _binary_mask(self, mask: MaskAnnotation, image: ImageAsset) -> BinaryMask:
        if mask.geometry_kind == "polygon":
            return _binary_mask_from_polygon(
                mask.polygon_json or [],
                width=image.width_px,
                height=image.height_px,
            )
        if mask.geometry_kind == "raster_mask":
            if not mask.mask_path:
                raise ValidationError("Raster mask content is missing")
            return _binary_mask_from_image(
                resolve_managed_project_path(self.settings, mask.mask_path),
                width=image.width_px,
                height=image.height_px,
            )
        raise ValidationError(
            f"Skeletonization is not supported for {mask.geometry_kind} masks"
        )

    @staticmethod
    def _readiness_for(
        mask: MaskAnnotation,
        binary: BinaryMask,
    ) -> SkeletonizationReadinessResponse:
        components = _connected_components_8(binary)
        total_pixels = sum(component.pixel_count for component in components)

        blocking_reason = None
        resolution_actions: list[SkeletonResolutionAction] = []
        if mask.status != "verified":
            blocking_reason = "mask_not_verified"
        elif not components:
            blocking_reason = "empty_mask"
        elif len(components) != 1:
            blocking_reason = "multiple_components"
            resolution_actions = [
                "repair_gap",
                "delete_artifact",
                "classify_separate_object",
            ]

        return SkeletonizationReadinessResponse(
            mask_annotation_id=mask.id,
            image_id=mask.image_id,
            mask_revision=mask.revision,
            geometry_kind=mask.geometry_kind,
            mask_status=mask.status,
            total_foreground_pixels=total_pixels,
            component_count=len(components),
            single_component=len(components) == 1,
            ready_for_skeletonization=blocking_reason is None,
            blocking_reason=blocking_reason,
            resolution_actions=resolution_actions,
            components=[
                SkeletonMaskComponentResponse(
                    index=index,
                    pixel_count=component.pixel_count,
                    x_min=component.x_min,
                    y_min=component.y_min,
                    x_max=component.x_max,
                    y_max=component.y_max,
                    touches_image_border=component.touches_image_border,
                )
                for index, component in enumerate(components, start=1)
            ],
        )

    def readiness(self, mask_annotation_id: str) -> SkeletonizationReadinessResponse:
        mask = self._mask(mask_annotation_id)
        image = self._image(mask.image_id)
        binary = self._binary_mask(mask, image)
        return self._readiness_for(mask, binary)

    def analysis(
        self,
        mask_annotation_id: str,
        *,
        terminal_spur_max_length_pixels: float = 0,
    ) -> SkeletonizationAnalysisResponse:
        mask = self._mask(mask_annotation_id)
        image = self._image(mask.image_id)
        binary = self._binary_mask(mask, image)
        readiness = self._readiness_for(mask, binary)
        if not readiness.ready_for_skeletonization:
            reason = readiness.blocking_reason or "unknown"
            raise ValidationError(
                f"Skeletonization is blocked until mask readiness is resolved: {reason}"
            )

        raw_skeleton, iterations = zhang_suen_thin(binary)
        skeleton_components = _connected_components_8(raw_skeleton)
        if len(skeleton_components) != 1:
            raise ValidationError(
                "Skeletonization changed mask connectivity; raw analysis was blocked"
            )

        features = classify_skeleton_pixels(raw_skeleton)
        if not features:
            raise ValidationError("Skeletonization produced an empty raw skeleton")

        isolated = sum(feature.kind == "isolated" for feature in features)
        endpoints = sum(feature.kind == "endpoint" for feature in features)
        paths = sum(feature.kind == "path" for feature in features)
        junctions = sum(feature.kind == "junction" for feature in features)
        junction_clusters = consolidate_junction_clusters(features)
        graph_nodes, graph_edges = build_initial_branch_graph(
            features,
            junction_clusters,
        )
        pruning = prune_terminal_spurs(
            raw_skeleton,
            max_length_pixels=terminal_spur_max_length_pixels,
        )
        pruned_data, _, _ = pruning.mask
        pruned_pixel_count = sum(value > 0 for value in pruned_data)

        calibration = _calibration_payload(image)
        raw_physical_lengths = _edge_physical_lengths(
            graph_nodes,
            graph_edges,
            calibration,
        )
        pruned_physical_lengths = _edge_physical_lengths(
            pruning.graph_nodes,
            pruning.graph_edges,
            calibration,
        )
        raw_tle_pixels = total_graph_length_pixels(graph_edges)
        pruned_tle_pixels = total_graph_length_pixels(pruning.graph_edges)
        raw_longest_pixels = graph_diameter_pixels(graph_nodes, graph_edges)
        pruned_longest_pixels = graph_diameter_pixels(
            pruning.graph_nodes,
            pruning.graph_edges,
        )
        raw_tle_physical = (
            sum(raw_physical_lengths.values()) if calibration is not None else None
        )
        pruned_tle_physical = (
            sum(pruned_physical_lengths.values()) if calibration is not None else None
        )
        raw_longest_physical = (
            _weighted_graph_diameter(
                graph_nodes,
                graph_edges,
                raw_physical_lengths,
            )
            if calibration is not None
            else None
        )
        pruned_longest_physical = (
            _weighted_graph_diameter(
                pruning.graph_nodes,
                pruning.graph_edges,
                pruned_physical_lengths,
            )
            if calibration is not None
            else None
        )
        raw_angles = _branch_angle_responses(
            graph_nodes,
            graph_edges,
            calibration,
        )
        pruned_angles = _branch_angle_responses(
            pruning.graph_nodes,
            pruning.graph_edges,
            calibration,
        )

        return SkeletonizationAnalysisResponse(
            mask_annotation_id=mask.id,
            image_id=mask.image_id,
            mask_revision=mask.revision,
            input_foreground_pixels=readiness.total_foreground_pixels,
            thinning_iterations=iterations,
            raw_skeleton_pixel_count=len(features),
            raw_skeleton_pixels=_pixel_coordinates(raw_skeleton),
            raw_skeleton_component_count=len(skeleton_components),
            topology_preserved=True,
            isolated_pixel_count=isolated,
            endpoint_count=endpoints,
            path_pixel_count=paths,
            junction_pixel_count=junctions,
            junction_cluster_count=len(junction_clusters),
            junction_clusters=[
                SkeletonJunctionClusterResponse(
                    id=cluster.id,
                    pixel_count=len(cluster.pixels),
                    centroid_x=cluster.centroid_x,
                    centroid_y=cluster.centroid_y,
                    representative_x=cluster.representative_x,
                    representative_y=cluster.representative_y,
                    external_connection_count=len(cluster.external_connections),
                )
                for cluster in junction_clusters
            ],
            graph_node_count=len(graph_nodes),
            graph_edge_count=len(graph_edges),
            graph_nodes=[
                SkeletonGraphNodeResponse(
                    id=node.id,
                    kind=node.kind,
                    x=node.x,
                    y=node.y,
                    source_pixel_count=len(node.source_pixels),
                    external_connection_count=node.external_connection_count,
                )
                for node in graph_nodes
            ],
            graph_edges=self._edge_responses(
                graph_nodes,
                graph_edges,
                raw_physical_lengths,
            ),
            terminal_spur_max_length_pixels=terminal_spur_max_length_pixels,
            spur_pruning_applied=bool(pruning.removals),
            spur_pruning_iteration_count=len(pruning.removals),
            removed_spur_count=len(pruning.removals),
            removed_spurs=[
                SkeletonSpurRemovalResponse(
                    iteration=removal.iteration,
                    branch_id=removal.branch_id,
                    endpoint_x=removal.endpoint_x,
                    endpoint_y=removal.endpoint_y,
                    junction_id=removal.junction_id,
                    branch_length_pixels=removal.branch_length_pixels,
                    removed_pixel_count=len(removal.removed_pixels),
                    removed_junction_boundary_pixel_count=(
                        removal.removed_junction_boundary_pixel_count
                    ),
                )
                for removal in pruning.removals
            ],
            pruned_skeleton_pixel_count=pruned_pixel_count,
            pruned_skeleton_pixels=_pixel_coordinates(pruning.mask),
            pruned_graph_node_count=len(pruning.graph_nodes),
            pruned_graph_edge_count=len(pruning.graph_edges),
            pruned_graph_nodes=[
                SkeletonGraphNodeResponse(
                    id=node.id,
                    kind=node.kind,
                    x=node.x,
                    y=node.y,
                    source_pixel_count=len(node.source_pixels),
                    external_connection_count=node.external_connection_count,
                )
                for node in pruning.graph_nodes
            ],
            pruned_graph_edges=self._edge_responses(
                pruning.graph_nodes,
                pruning.graph_edges,
                pruned_physical_lengths,
            ),
            raw_branch_count=len(graph_edges),
            pruned_branch_count=len(pruning.graph_edges),
            raw_total_linear_extension_pixels=raw_tle_pixels,
            pruned_total_linear_extension_pixels=pruned_tle_pixels,
            raw_total_linear_extension_physical=raw_tle_physical,
            pruned_total_linear_extension_physical=pruned_tle_physical,
            raw_longest_path_pixels=raw_longest_pixels,
            pruned_longest_path_pixels=pruned_longest_pixels,
            raw_longest_path_physical=raw_longest_physical,
            pruned_longest_path_physical=pruned_longest_physical,
            raw_branch_angles=raw_angles,
            pruned_branch_angles=pruned_angles,
            branch_angle_space=(
                "reference_plane"
                if calibration is not None
                and calibration.perspective_homography is not None
                else "image_pixels"
            ),
            calibrated=calibration is not None,
            physical_unit=calibration.unit if calibration is not None else None,
            distance_per_pixel=(
                calibration.distance_per_pixel if calibration is not None else None
            ),
            calibration_source=(
                calibration.source if calibration is not None else None
            ),
            calibration_confidence=(
                calibration.confidence if calibration is not None else None
            ),
            perspective_corrected=(
                calibration is not None
                and calibration.perspective_homography is not None
            ),
            length_calibration_method=(
                "reference_plane_homography"
                if calibration is not None
                and calibration.perspective_homography is not None
                else (
                    "scalar_distance_per_pixel"
                    if calibration is not None
                    else "pixel_only"
                )
            ),
            reference_plane_only=(
                calibration.reference_plane_only
                if calibration is not None
                else None
            ),
            final_skeleton_source="automatic_pruned",
            human_correction_applied=False,
            final_skeleton_pixels=_pixel_coordinates(pruning.mask),
            final_graph_nodes=[
                SkeletonGraphNodeResponse(
                    id=node.id,
                    kind=node.kind,
                    x=node.x,
                    y=node.y,
                    source_pixel_count=len(node.source_pixels),
                    external_connection_count=node.external_connection_count,
                )
                for node in pruning.graph_nodes
            ],
            final_graph_edges=self._edge_responses(
                pruning.graph_nodes,
                pruning.graph_edges,
                pruned_physical_lengths,
            ),
            final_branch_count=len(pruning.graph_edges),
            final_total_linear_extension_pixels=pruned_tle_pixels,
            final_total_linear_extension_physical=pruned_tle_physical,
            final_longest_path_pixels=pruned_longest_pixels,
            final_longest_path_physical=pruned_longest_physical,
            final_branch_angles=pruned_angles,
            feature_pixels=[
                SkeletonFeaturePixelResponse(
                    x=feature.x,
                    y=feature.y,
                    degree=feature.degree,
                    kind=feature.kind,
                )
                for feature in features
                if feature.kind != "path"
            ],
        )

    def _analysis_record(
        self,
        analysis_id: str,
    ) -> SkeletonAnalysisRevision:
        record = self.session.get(SkeletonAnalysisRevision, analysis_id)
        if record is None:
            raise NotFoundError("Skeleton analysis revision not found")
        return record

    def _analysis_record_response(
        self,
        record: SkeletonAnalysisRevision,
    ) -> SkeletonAnalysisRevisionResponse:
        mask = self._mask(record.mask_annotation_id)
        image = self._image(record.image_id)
        current_calibration_sha256 = _calibration_sha256(image)
        current_input_mask_sha256 = _binary_mask_sha256(
            self._binary_mask(mask, image)
        )
        stale_mask = current_input_mask_sha256 != record.input_mask_sha256
        stale_calibration = current_calibration_sha256 != record.calibration_sha256
        return SkeletonAnalysisRevisionResponse(
            id=record.id,
            analysis_series_id=record.analysis_series_id,
            analysis_revision=record.analysis_revision,
            supersedes_analysis_id=record.supersedes_analysis_id,
            mask_annotation_id=record.mask_annotation_id,
            image_id=record.image_id,
            mask_revision=record.mask_revision,
            current_mask_revision=mask.revision,
            source_kind=record.source_kind,
            algorithm=record.algorithm,
            algorithm_version=record.algorithm_version,
            terminal_spur_max_length_pixels=(
                record.terminal_spur_max_length_pixels
            ),
            input_mask_sha256=record.input_mask_sha256,
            calibration_sha256=record.calibration_sha256,
            parameters_sha256=record.parameters_sha256,
            result_sha256=record.result_sha256,
            result=SkeletonizationAnalysisResponse.model_validate(
                record.result_json
            ),
            correction=dict(record.correction_json or {}),
            review_status=record.review_status,
            reviewed_by=record.reviewed_by,
            reviewed_at=record.reviewed_at,
            review_note=record.review_note,
            created_by=record.created_by,
            created_at=record.created_at,
            stale_mask=stale_mask,
            stale_calibration=stale_calibration,
            stale=stale_mask or stale_calibration,
        )

    def persist_analysis(
        self,
        mask_annotation_id: str,
        payload: SkeletonAnalysisCreateRequest,
    ) -> SkeletonAnalysisRevisionResponse:
        mask = self._mask(mask_annotation_id)
        image = self._image(mask.image_id)
        binary = self._binary_mask(mask, image)
        input_mask_sha256 = _binary_mask_sha256(binary)
        calibration_sha256 = _calibration_sha256(image)
        parameters_sha256 = _analysis_parameters_sha256(
            payload.terminal_spur_max_length_pixels
        )
        result = self.analysis(
            mask.id,
            terminal_spur_max_length_pixels=(
                payload.terminal_spur_max_length_pixels
            ),
        )
        result_json = result.model_dump(mode="json")
        result_sha256 = canonical_json_sha256(result_json)

        existing = self.session.scalar(
            select(SkeletonAnalysisRevision)
            .where(
                SkeletonAnalysisRevision.mask_annotation_id == mask.id,
                SkeletonAnalysisRevision.mask_revision == mask.revision,
                SkeletonAnalysisRevision.source_kind == "automatic",
                SkeletonAnalysisRevision.input_mask_sha256 == input_mask_sha256,
                SkeletonAnalysisRevision.calibration_sha256 == calibration_sha256,
                SkeletonAnalysisRevision.parameters_sha256 == parameters_sha256,
                SkeletonAnalysisRevision.result_sha256 == result_sha256,
            )
            .order_by(
                SkeletonAnalysisRevision.created_at.desc(),
                SkeletonAnalysisRevision.id.desc(),
            )
            .limit(1)
        )
        if existing is not None:
            return self._analysis_record_response(existing)

        record = SkeletonAnalysisRevision(
            analysis_series_id=str(uuid4()),
            analysis_revision=1,
            supersedes_analysis_id=None,
            mask_annotation_id=mask.id,
            image_id=mask.image_id,
            mask_revision=mask.revision,
            source_kind="automatic",
            algorithm=result.algorithm,
            algorithm_version=result.algorithm_version,
            terminal_spur_max_length_pixels=(
                payload.terminal_spur_max_length_pixels
            ),
            input_mask_sha256=input_mask_sha256,
            calibration_sha256=calibration_sha256,
            parameters_sha256=parameters_sha256,
            result_sha256=result_sha256,
            result_json=result_json,
            correction_json={},
            review_status="unreviewed",
            created_by="local_user",
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._analysis_record_response(record)

    def get_persisted_analysis(
        self,
        analysis_id: str,
    ) -> SkeletonAnalysisRevisionResponse:
        return self._analysis_record_response(
            self._analysis_record(analysis_id)
        )

    def list_persisted_analyses(
        self,
        mask_annotation_id: str,
    ) -> list[SkeletonAnalysisRevisionResponse]:
        self._mask(mask_annotation_id)
        statement = (
            select(SkeletonAnalysisRevision)
            .where(
                SkeletonAnalysisRevision.mask_annotation_id
                == mask_annotation_id
            )
            .order_by(
                SkeletonAnalysisRevision.created_at,
                SkeletonAnalysisRevision.analysis_series_id,
                SkeletonAnalysisRevision.analysis_revision,
            )
        )
        return [
            self._analysis_record_response(record)
            for record in self.session.scalars(statement)
        ]

    def review_persisted_analysis(
        self,
        analysis_id: str,
        payload: SkeletonAnalysisReviewRequest,
    ) -> SkeletonAnalysisRevisionResponse:
        record = self._analysis_record(analysis_id)
        response = self._analysis_record_response(record)
        if response.stale:
            raise ValidationError(
                "Stale skeleton analyses must be regenerated before review"
            )
        record.review_status = payload.review_status
        record.reviewed_by = "local_user"
        record.reviewed_at = utc_now()
        record.review_note = payload.note
        self.session.commit()
        self.session.refresh(record)
        return self._analysis_record_response(record)

    def correct_persisted_analysis(
        self,
        analysis_id: str,
        payload: SkeletonAnalysisCorrectionRequest,
    ) -> SkeletonAnalysisRevisionResponse:
        base = self._analysis_record(analysis_id)
        base_response = self._analysis_record_response(base)
        if base_response.stale:
            raise ValidationError(
                "Stale skeleton analyses must be regenerated before correction"
            )

        latest = self.session.scalar(
            select(SkeletonAnalysisRevision)
            .where(
                SkeletonAnalysisRevision.analysis_series_id
                == base.analysis_series_id
            )
            .order_by(
                SkeletonAnalysisRevision.analysis_revision.desc(),
                SkeletonAnalysisRevision.created_at.desc(),
                SkeletonAnalysisRevision.id.desc(),
            )
            .limit(1)
        )
        if latest is None or latest.id != base.id:
            raise ValidationError(
                "Skeleton corrections must be based on the latest analysis revision"
            )

        add_pixels = {(item.x, item.y) for item in payload.add_pixels}
        remove_pixels = {(item.x, item.y) for item in payload.remove_pixels}
        if not add_pixels and not remove_pixels:
            raise ValidationError("Skeleton correction must change at least one pixel")
        if add_pixels & remove_pixels:
            raise ValidationError(
                "A skeleton pixel cannot be both added and removed"
            )

        image = self._image(base.image_id)
        for x, y in add_pixels | remove_pixels:
            if x >= image.width_px or y >= image.height_px:
                raise ValidationError("Skeleton correction pixel is outside the image")

        current_pixels = {
            (point.x, point.y)
            for point in base_response.result.final_skeleton_pixels
        }
        missing_removals = remove_pixels - current_pixels
        if missing_removals:
            raise ValidationError(
                "Skeleton correction can only remove existing final pixels"
            )
        duplicate_additions = add_pixels & current_pixels
        if duplicate_additions:
            raise ValidationError(
                "Skeleton correction can only add pixels not already present"
            )

        corrected_pixels = (current_pixels - remove_pixels) | add_pixels
        if not corrected_pixels:
            raise ValidationError("Skeleton correction cannot remove every pixel")

        corrected_data = bytearray(image.width_px * image.height_px)
        for x, y in corrected_pixels:
            corrected_data[y * image.width_px + x] = 255
        corrected_mask: BinaryMask = (
            bytes(corrected_data),
            image.width_px,
            image.height_px,
        )
        corrected_components = _connected_components_8(corrected_mask)
        if len(corrected_components) != 1:
            raise ValidationError(
                "Corrected skeleton must remain one 8-connected component"
            )

        features = classify_skeleton_pixels(corrected_mask)
        clusters = consolidate_junction_clusters(features)
        nodes, edges = build_initial_branch_graph(features, clusters)
        calibration = _calibration_payload(image)
        physical_lengths = _edge_physical_lengths(
            nodes,
            edges,
            calibration,
        )
        tle_pixels = total_graph_length_pixels(edges)
        longest_pixels = graph_diameter_pixels(nodes, edges)
        tle_physical = (
            sum(physical_lengths.values()) if calibration is not None else None
        )
        longest_physical = (
            _weighted_graph_diameter(nodes, edges, physical_lengths)
            if calibration is not None
            else None
        )
        angles = _branch_angle_responses(nodes, edges, calibration)

        corrected_result = base_response.result.model_copy(deep=True)
        corrected_result.final_skeleton_source = "human_corrected"
        corrected_result.human_correction_applied = True
        corrected_result.final_skeleton_pixels = _pixel_coordinates(
            corrected_mask
        )
        corrected_result.final_graph_nodes = [
            SkeletonGraphNodeResponse(
                id=node.id,
                kind=node.kind,
                x=node.x,
                y=node.y,
                source_pixel_count=len(node.source_pixels),
                external_connection_count=node.external_connection_count,
            )
            for node in nodes
        ]
        corrected_result.final_graph_edges = self._edge_responses(
            nodes,
            edges,
            physical_lengths,
        )
        corrected_result.final_branch_count = len(edges)
        corrected_result.final_total_linear_extension_pixels = tle_pixels
        corrected_result.final_total_linear_extension_physical = tle_physical
        corrected_result.final_longest_path_pixels = longest_pixels
        corrected_result.final_longest_path_physical = longest_physical
        corrected_result.final_branch_angles = angles

        result_json = corrected_result.model_dump(mode="json")
        result_sha256 = canonical_json_sha256(result_json)
        correction_json = {
            "schema_version": "skeleton-correction-0001",
            "base_analysis_id": base.id,
            "base_result_sha256": base.result_sha256,
            "reason_code": payload.reason_code,
            "note": payload.note,
            "add_pixels": [
                {"x": x, "y": y}
                for x, y in sorted(add_pixels, key=lambda point: (point[1], point[0]))
            ],
            "remove_pixels": [
                {"x": x, "y": y}
                for x, y in sorted(
                    remove_pixels,
                    key=lambda point: (point[1], point[0]),
                )
            ],
        }

        record = SkeletonAnalysisRevision(
            analysis_series_id=base.analysis_series_id,
            analysis_revision=base.analysis_revision + 1,
            supersedes_analysis_id=base.id,
            mask_annotation_id=base.mask_annotation_id,
            image_id=base.image_id,
            mask_revision=base.mask_revision,
            source_kind="human_corrected",
            algorithm=base.algorithm,
            algorithm_version=base.algorithm_version,
            terminal_spur_max_length_pixels=(
                base.terminal_spur_max_length_pixels
            ),
            input_mask_sha256=base.input_mask_sha256,
            calibration_sha256=base.calibration_sha256,
            parameters_sha256=base.parameters_sha256,
            result_sha256=result_sha256,
            result_json=result_json,
            correction_json=correction_json,
            review_status="unreviewed",
            created_by="local_user",
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._analysis_record_response(record)

    def export_persisted_analysis(
        self,
        analysis_id: str,
    ) -> SkeletonAnalysisExportResponse:
        record = self._analysis_record_response(
            self._analysis_record(analysis_id)
        )
        if record.stale:
            raise ValidationError(
                "Stale skeleton analyses must be regenerated before export"
            )
        if record.review_status != "approved":
            raise ValidationError(
                "Only approved skeleton analyses can be exported"
            )

        image = self._image(record.image_id)
        project = self.session.get(Project, image.project_id)
        if project is None:
            raise NotFoundError("Project not found")
        export_root = resolve_managed_project_path(
            self.settings,
            f"{project.storage_root}/skeletonization/exports",
        )
        exported = build_skeleton_export(
            export_root=export_root,
            record=record,
        )
        return SkeletonAnalysisExportResponse(
            analysis_id=record.id,
            analysis_revision=record.analysis_revision,
            package_name=exported["package_dir"].name,
            archive_name=exported["archive_path"].name,
            archive_size_bytes=exported["archive_size_bytes"],
            archive_sha256=exported["archive_sha256"],
            manifest_sha256=exported["manifest_sha256"],
        )

    def persisted_analysis_archive_path(
        self,
        analysis_id: str,
    ) -> Path:
        record = self._analysis_record_response(
            self._analysis_record(analysis_id)
        )
        if record.stale:
            raise ValidationError(
                "Stale skeleton analyses must be regenerated before download"
            )
        if record.review_status != "approved":
            raise ValidationError(
                "Only approved skeleton analyses can be downloaded"
            )

        image = self._image(record.image_id)
        project = self.session.get(Project, image.project_id)
        if project is None:
            raise NotFoundError("Project not found")
        export_root = resolve_managed_project_path(
            self.settings,
            f"{project.storage_root}/skeletonization/exports",
        )
        archive = export_root / f"{skeleton_export_stem(record.id)}.zip"
        if not archive.is_file():
            raise NotFoundError("Skeleton analysis export archive not found")
        return archive

