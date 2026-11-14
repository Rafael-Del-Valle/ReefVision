"""Public contracts for ReefVision annotation aggregates."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AnnotationClassAggregate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label_class_id: UUID | None
    label_name: str
    box_count: int = Field(ge=0)
    verified_mask_count: int = Field(ge=0)
    draft_or_unverified_mask_count: int = Field(ge=0)
    known_mask_area_px2_sum: int = Field(ge=0)
    mask_area_unknown_count: int = Field(ge=0)
    boxes_by_source: dict[str, int]
    verified_masks_by_geometry: dict[str, int]


class AnnotationImageAggregate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    project_id: UUID
    image_id: UUID
    image_sha256: str
    image_annotation_revision: int = Field(ge=0)
    image_annotation_status: str
    image_width_px: int = Field(gt=0)
    image_height_px: int = Field(gt=0)
    classes: list[AnnotationClassAggregate]
    total_saved_box_count: int = Field(ge=0)
    total_verified_mask_count: int = Field(ge=0)
    total_unverified_mask_count: int = Field(ge=0)
    prediction_proposals_by_review_status: dict[str, int]
    snapshot_sha256: str
    methodological_notes: list[str]
