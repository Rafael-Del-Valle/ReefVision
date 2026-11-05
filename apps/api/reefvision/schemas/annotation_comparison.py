"""Typed contracts for descriptive annotation-source comparisons."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AnnotationComparisonSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["reviewed_boxes", "prediction_job"]
    prediction_job_id: UUID | None = None

    @model_validator(mode="after")
    def require_job_only_for_prediction_source(self) -> AnnotationComparisonSource:
        if (self.kind == "prediction_job") != (self.prediction_job_id is not None):
            raise ValueError("prediction_job sources require exactly one prediction_job_id")
        return self


class AnnotationComparisonPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_id: UUID
    source_a: AnnotationComparisonSource
    source_b: AnnotationComparisonSource
    reference_side: Literal["a", "b"] | None = None
    iou_threshold: float = Field(default=0.5, gt=0, le=1)


class AnnotationComparisonCalculateRequest(AnnotationComparisonPreviewRequest):
    name: str = Field(min_length=1, max_length=200)


class AnnotationComparisonPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.1.0"] = "1.1.0"
    algorithm: Literal["reefvision.class-aware-box-comparison.v1"]
    project_id: UUID
    image_id: UUID
    image_sha256: str
    source_a: AnnotationComparisonSource
    source_b: AnnotationComparisonSource
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
