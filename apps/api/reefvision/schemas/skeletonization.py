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
