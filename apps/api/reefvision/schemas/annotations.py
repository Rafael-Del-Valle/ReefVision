"""Annotation editor request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    field_validator,
    model_validator,
)

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


class PolygonPoint(BaseModel):
    x: FiniteFloat
    y: FiniteFloat


class MaskAnnotationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    image_id: str
    label_class_id: str | None
    geometry_kind: str
    mask_path: str | None
    polygon_json: list[list[float]] | None
    x_min: float | None
    y_min: float | None
    x_max: float | None
    y_max: float | None
    area_pixels: int | None
    source_type: str
    provenance_json: dict[str, Any] | None
    status: str
    created_by: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    revision: int


class MaskAnnotationDraft(BaseModel):
    id: str = Field(min_length=1, max_length=36)
    label_class_id: str = Field(min_length=1, max_length=36)
    geometry_kind: Literal["polygon", "rotated_box"] = "polygon"
    points: list[PolygonPoint] = Field(min_length=3, max_length=100_000)
    status: Literal["draft"] | None = None

    @field_validator("points")
    @classmethod
    def require_three_unique_points(
        cls,
        value: list[PolygonPoint],
    ) -> list[PolygonPoint]:
        unique = {(float(point.x), float(point.y)) for point in value}
        if len(unique) < 3:
            raise ValueError("Polygon masks require at least three unique points")
        return value

    @model_validator(mode="after")
    def validate_geometry_point_count(self) -> MaskAnnotationDraft:
        if self.geometry_kind == "rotated_box" and len(self.points) != 4:
            raise ValueError("Rotated boxes require exactly four corner points")
        return self


class AnnotationCountResponse(BaseModel):
    label_class_id: str
    count: int = Field(ge=0)


class AnnotationSessionResponse(BaseModel):
    image: ImageResponse
    label_classes: list[LabelClassResponse]
    annotations: list[AnnotationResponse]
    mask_annotations: list[MaskAnnotationResponse] = Field(default_factory=list)
    counts_by_class: list[AnnotationCountResponse]
    mask_counts_by_class: list[AnnotationCountResponse] = Field(default_factory=list)
    previous_image_id: str | None
    next_image_id: str | None


class AnnotationBatchSaveRequest(BaseModel):
    base_revision: int = Field(ge=0)
    annotation_status: AnnotationStatus
    annotations: list[AnnotationDraft]
    mask_annotations: list[MaskAnnotationDraft] = Field(default_factory=list)
    deleted_mask_annotation_ids: list[str] = Field(default_factory=list)

    @field_validator("annotations")
    @classmethod
    def unique_annotation_ids(
        cls,
        value: list[AnnotationDraft],
    ) -> list[AnnotationDraft]:
        ids = [item.id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("Annotation ids must be unique within one save request")
        return value

    @field_validator("mask_annotations")
    @classmethod
    def unique_mask_annotation_ids(
        cls,
        value: list[MaskAnnotationDraft],
    ) -> list[MaskAnnotationDraft]:
        ids = [item.id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("Mask annotation ids must be unique within one save request")
        return value

    @field_validator("deleted_mask_annotation_ids")
    @classmethod
    def unique_deleted_mask_annotation_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Deleted mask annotation ids must be unique")
        return value

    @model_validator(mode="after")
    def edited_masks_may_not_also_be_deleted(self) -> AnnotationBatchSaveRequest:
        active_ids = {item.id for item in self.mask_annotations}
        deleted_ids = set(self.deleted_mask_annotation_ids)
        if active_ids & deleted_ids:
            raise ValueError("A mask annotation cannot be edited and deleted in the same save")
        return self


class AnnotationBatchSaveResponse(BaseModel):
    image: ImageResponse
    annotations: list[AnnotationResponse]
    mask_annotations: list[MaskAnnotationResponse] = Field(default_factory=list)
    counts_by_class: list[AnnotationCountResponse]
    mask_counts_by_class: list[AnnotationCountResponse] = Field(default_factory=list)


AnnotationSnapshot = dict[str, Any]
