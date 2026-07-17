"""Prediction proposal and review API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, FiniteFloat, field_validator

from reefvision.schemas.annotations import (
    AnnotationResponse,
    MaskAnnotationResponse,
)


class PredictionProposalResponse(BaseModel):
    id: str
    project_id: str
    image_id: str
    model_id: str
    model_display_name: str
    inference_job_id: str
    model_checksum: str
    label_class_id: str | None
    predicted_label: str
    predicted_index: int | None
    confidence: float
    geometry_kind: str = "bounding_box"
    polygon_json: list[list[float]] | None = None
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    review_status: str
    was_edited: bool
    reviewer_action_at: datetime | None
    accepted_annotation_id: str | None
    accepted_mask_annotation_id: str | None = None
    inference_settings_json: dict[str, Any]
    provenance_json: dict[str, Any] | None
    created_at: datetime


class PredictionListResponse(BaseModel):
    items: list[PredictionProposalResponse]
    counts: dict[str, int]


class PredictionAcceptRequest(BaseModel):
    label_class_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=36,
    )
    x_min: FiniteFloat | None = None
    y_min: FiniteFloat | None = None
    x_max: FiniteFloat | None = None
    y_max: FiniteFloat | None = None
    polygon_json: list[list[FiniteFloat]] | None = Field(
        default=None,
        min_length=3,
    )

    @field_validator("polygon_json")
    @classmethod
    def validate_polygon_points(
        cls,
        value: list[list[FiniteFloat]] | None,
    ) -> list[list[FiniteFloat]] | None:
        if value is not None and any(len(point) != 2 for point in value):
            raise ValueError(
                "Every segmentation polygon point must contain x and y"
            )
        return value


class PredictionReviewResponse(BaseModel):
    proposal: PredictionProposalResponse
    annotation: AnnotationResponse | None
    mask_annotation: MaskAnnotationResponse | None = None


class PredictionBulkReviewRequest(BaseModel):
    action: Literal["accept", "reject"]
    proposal_ids: list[str] = Field(min_length=1)

    @field_validator("proposal_ids")
    @classmethod
    def unique_ids(cls, value: list[str]) -> list[str]:
        ids = [item for item in value if item]
        if len(ids) != len(set(ids)):
            raise ValueError("Proposal ids must be unique")
        return ids


class PredictionBulkReviewResponse(BaseModel):
    reviewed_count: int
    created_annotations: list[AnnotationResponse]
    created_mask_annotations: list[MaskAnnotationResponse] = Field(
        default_factory=list
    )
