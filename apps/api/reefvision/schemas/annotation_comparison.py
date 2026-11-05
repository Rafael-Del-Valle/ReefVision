"""Typed contracts for descriptive annotation-source comparisons."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AnnotationComparisonSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["reviewed_boxes", "verified_masks", "prediction_job"]
    prediction_job_id: UUID | None = None
    mask_annotation_ids: list[UUID] = Field(default_factory=list, max_length=5000)

    @model_validator(mode="after")
    def validate_source_identity(self) -> AnnotationComparisonSource:
        if (self.kind == "prediction_job") != (self.prediction_job_id is not None):
            raise ValueError("prediction_job sources require exactly one prediction_job_id")
        if self.kind == "verified_masks":
            if not self.mask_annotation_ids:
                raise ValueError("verified_masks sources require explicit mask_annotation_ids")
            if len(set(self.mask_annotation_ids)) != len(self.mask_annotation_ids):
                raise ValueError("mask_annotation_ids must be unique")
        elif self.mask_annotation_ids:
            raise ValueError("mask_annotation_ids are only valid for verified_masks sources")
        return self


class AnnotationComparisonPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_id: UUID
    source_a: AnnotationComparisonSource
    source_b: AnnotationComparisonSource
    geometry_kind: Literal["boxes", "masks"] = "boxes"
    reference_side: Literal["a", "b"] | None = None
    iou_threshold: float = Field(default=0.5, gt=0, le=1)

    @model_validator(mode="after")
    def validate_geometry_sources(self) -> AnnotationComparisonPreviewRequest:
        allowed = (
            {"reviewed_boxes", "prediction_job"}
            if self.geometry_kind == "boxes"
            else {"verified_masks", "prediction_job"}
        )
        if self.source_a.kind not in allowed or self.source_b.kind not in allowed:
            raise ValueError(f"Source kind is incompatible with {self.geometry_kind} comparison")
        if self.geometry_kind == "masks":
            shared = set(self.source_a.mask_annotation_ids) & set(self.source_b.mask_annotation_ids)
            if shared:
                raise ValueError("Mask source inventories must be independently identifiable")
        return self


class AnnotationComparisonCalculateRequest(AnnotationComparisonPreviewRequest):
    name: str = Field(min_length=1, max_length=200)


class AnnotationComparisonPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.1.0"] = "1.1.0"
    algorithm: Literal[
        "reefvision.class-aware-box-comparison.v1",
        "reefvision.class-aware-mask-comparison.v1",
    ]
    project_id: UUID
    image_id: UUID
    image_sha256: str
    source_a: AnnotationComparisonSource
    source_b: AnnotationComparisonSource
    geometry_kind: Literal["boxes", "masks"]
    source_a_snapshot: list[dict[str, Any]]
    source_b_snapshot: list[dict[str, Any]]
    source_a_sha256: str = Field(min_length=64, max_length=64)
    source_b_sha256: str = Field(min_length=64, max_length=64)
    iou_threshold: float
    reference_side: Literal["a", "b"] | None
    per_class: dict[str, dict[str, Any]]
    independent_sampling_unit: Literal["image"]
    content_sha256: str = Field(min_length=64, max_length=64)
    methodological_notes: list[str]


class AnnotationComparisonSavedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition_id: UUID
    result_id: UUID
    definition_sha256: str = Field(min_length=64, max_length=64)
    result_sha256: str = Field(min_length=64, max_length=64)
    comparison: AnnotationComparisonPreviewResponse


class AnnotationComparisonValidationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_id: UUID
    is_current: bool
    reasons: list[str]
    stored_comparison_sha256: str = Field(min_length=64, max_length=64)
    current_comparison_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    validated_at: datetime
