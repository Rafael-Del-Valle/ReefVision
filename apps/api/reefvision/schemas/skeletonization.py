"""Schemas for conservative coral skeletonization readiness and analysis."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SkeletonBlockingReason = Literal[
    "mask_not_verified",
    "empty_mask",
    "multiple_components",
]
SkeletonResolutionAction = Literal[
    "repair_gap",
    "delete_artifact",
    "classify_separate_object",
]


class SkeletonMaskComponentResponse(BaseModel):
    index: int = Field(ge=1)
    pixel_count: int = Field(ge=1)
    x_min: int = Field(ge=0)
    y_min: int = Field(ge=0)
    x_max: int = Field(ge=0)
    y_max: int = Field(ge=0)
    touches_image_border: bool = False


class SkeletonizationReadinessResponse(BaseModel):
    schema_version: Literal["skeleton-readiness-0001"] = "skeleton-readiness-0001"
    mask_annotation_id: str
    image_id: str
    mask_revision: int = Field(ge=1)
    geometry_kind: str
    mask_status: str
    connectivity: Literal[8] = 8
    total_foreground_pixels: int = Field(ge=0)
    component_count: int = Field(ge=0)
    single_component: bool
    ready_for_skeletonization: bool
    blocking_reason: SkeletonBlockingReason | None = None
    resolution_actions: list[SkeletonResolutionAction] = Field(default_factory=list)
    automatic_bridge_applied: Literal[False] = False
    components: list[SkeletonMaskComponentResponse] = Field(default_factory=list)


SkeletonPixelKind = Literal["isolated", "endpoint", "path", "junction"]


class SkeletonFeaturePixelResponse(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    degree: int = Field(ge=0, le=8)
    kind: SkeletonPixelKind


class SkeletonJunctionClusterResponse(BaseModel):
    id: str
    pixel_count: int = Field(ge=1)
    centroid_x: float = Field(ge=0)
    centroid_y: float = Field(ge=0)
    representative_x: int = Field(ge=0)
    representative_y: int = Field(ge=0)
    external_connection_count: int = Field(ge=0)


SkeletonGraphNodeKind = Literal["endpoint", "junction", "isolated", "cycle_anchor"]


class SkeletonGraphNodeResponse(BaseModel):
    id: str
    kind: SkeletonGraphNodeKind
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    source_pixel_count: int = Field(ge=1)
    external_connection_count: int = Field(ge=0)


class SkeletonGraphEdgeResponse(BaseModel):
    id: str
    source_node_id: str
    target_node_id: str
    path_pixel_count: int = Field(ge=2)
    boundary_to_boundary_length_pixels: float = Field(gt=0)
    is_cycle: bool = False


class SkeletonSpurRemovalResponse(BaseModel):
    iteration: int = Field(ge=1)
    branch_id: str
    endpoint_x: int = Field(ge=0)
    endpoint_y: int = Field(ge=0)
    junction_id: str
    branch_length_pixels: float = Field(gt=0)
    removed_pixel_count: int = Field(ge=1)
    removed_junction_boundary_pixel_count: int = Field(ge=0)


class SkeletonizationAnalysisResponse(BaseModel):
    schema_version: Literal["skeleton-analysis-0001"] = "skeleton-analysis-0001"
    mask_annotation_id: str
    image_id: str
    mask_revision: int = Field(ge=1)
    algorithm: Literal["zhang_suen"] = "zhang_suen"
    algorithm_version: Literal["0001"] = "0001"
    connectivity: Literal[8] = 8
    pre_thinning_cleanup: Literal["binary_normalization_only"] = (
        "binary_normalization_only"
    )
    cleanup_removed_pixels: Literal[0] = 0
    automatic_bridge_applied: Literal[False] = False
    input_foreground_pixels: int = Field(ge=1)
    thinning_iterations: int = Field(ge=0)
    raw_skeleton_pixel_count: int = Field(ge=1)
    raw_skeleton_component_count: int = Field(ge=1)
    topology_preserved: bool
    isolated_pixel_count: int = Field(ge=0)
    endpoint_count: int = Field(ge=0)
    path_pixel_count: int = Field(ge=0)
    junction_pixel_count: int = Field(ge=0)
    junction_cluster_count: int = Field(ge=0)
    junction_clusters: list[SkeletonJunctionClusterResponse] = Field(default_factory=list)
    graph_node_count: int = Field(ge=1)
    graph_edge_count: int = Field(ge=0)
    graph_nodes: list[SkeletonGraphNodeResponse] = Field(default_factory=list)
    graph_edges: list[SkeletonGraphEdgeResponse] = Field(default_factory=list)
    terminal_spur_max_length_pixels: float = Field(default=0, ge=0)
    spur_pruning_applied: bool = False
    spur_pruning_iteration_count: int = Field(default=0, ge=0)
    removed_spur_count: int = Field(default=0, ge=0)
    removed_spurs: list[SkeletonSpurRemovalResponse] = Field(default_factory=list)
    pruned_skeleton_pixel_count: int = Field(ge=1)
    pruned_graph_node_count: int = Field(ge=1)
    pruned_graph_edge_count: int = Field(ge=0)
    pruned_graph_nodes: list[SkeletonGraphNodeResponse] = Field(default_factory=list)
    pruned_graph_edges: list[SkeletonGraphEdgeResponse] = Field(default_factory=list)
    feature_pixels: list[SkeletonFeaturePixelResponse] = Field(default_factory=list)
