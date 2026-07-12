"""Annotation editor request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator

from reefvision.domain.enums import AnnotationStatus
from reefvision.schemas.images import ImageResponse
from reefvision.schemas.projects import LabelClassResponse


class AnnotationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    image_id: str
    label_class_id: str
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    source_type: str
    source_model_id: str | None
    source_prediction_id: str | None
    provenance_json: dict[str, Any] | None
    created_by: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    revision: int


class AnnotationDraft(BaseModel):
    id: str = Field(min_length=1, max_length=36)
    label_class_id: str = Field(min_length=1, max_length=36)
    x_min: FiniteFloat
    y_min: FiniteFloat
    x_max: FiniteFloat
    y_max: FiniteFloat


class AnnotationCountResponse(BaseModel):
    label_class_id: str
    count: int = Field(ge=0)


class AnnotationSessionResponse(BaseModel):
    image: ImageResponse
    label_classes: list[LabelClassResponse]
    annotations: list[AnnotationResponse]
    counts_by_class: list[AnnotationCountResponse]
    previous_image_id: str | None
    next_image_id: str | None


class AnnotationBatchSaveRequest(BaseModel):
    base_revision: int = Field(ge=0)
    annotation_status: AnnotationStatus
    annotations: list[AnnotationDraft]

    @field_validator("annotations")
    @classmethod
    def unique_annotation_ids(cls, value: list[AnnotationDraft]) -> list[AnnotationDraft]:
        ids = [item.id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("Annotation ids must be unique within one save request")
        return value


class AnnotationBatchSaveResponse(BaseModel):
    image: ImageResponse
    annotations: list[AnnotationResponse]
    counts_by_class: list[AnnotationCountResponse]


AnnotationSnapshot = dict[str, Any]
