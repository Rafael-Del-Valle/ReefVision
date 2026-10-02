"""Conservative coral skeletonization readiness and raw analysis."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, UnidentifiedImageError
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import ImageAsset, MaskAnnotation
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.repositories.mask_annotations import MaskAnnotationRepository
from reefvision.schemas.skeletonization import (
    SkeletonFeaturePixelResponse,
    SkeletonGraphEdgeResponse,
    SkeletonGraphNodeResponse,
    SkeletonizationAnalysisResponse,
    SkeletonizationReadinessResponse,
    SkeletonJunctionClusterResponse,
    SkeletonMaskComponentResponse,
    SkeletonResolutionAction,
)
from reefvision.services.skeleton_algorithms import (
    BinaryMask,
    build_initial_branch_graph,
    classify_skeleton_pixels,
    consolidate_junction_clusters,
    zhang_suen_thin,
)
from reefvision.storage.projects import resolve_managed_project_path


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

    def analysis(self, mask_annotation_id: str) -> SkeletonizationAnalysisResponse:
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

        return SkeletonizationAnalysisResponse(
            mask_annotation_id=mask.id,
            image_id=mask.image_id,
            mask_revision=mask.revision,
            input_foreground_pixels=readiness.total_foreground_pixels,
            thinning_iterations=iterations,
            raw_skeleton_pixel_count=len(features),
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
            graph_edges=[
                SkeletonGraphEdgeResponse(
                    id=edge.id,
                    source_node_id=edge.source_node_id,
                    target_node_id=edge.target_node_id,
                    path_pixel_count=len(edge.pixels),
                    boundary_to_boundary_length_pixels=(
                        edge.boundary_to_boundary_length_pixels
                    ),
                    is_cycle=edge.is_cycle,
                )
                for edge in graph_edges
            ],
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
