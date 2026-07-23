"""Classification dataset, training, inference, review, and assignment schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ClassificationMode = Literal["multiclass", "binary_state"]
ClassificationReviewStatus = Literal["pending", "accepted", "rejected"]
ClassificationTargetKind = Literal["annotation", "image", "mask", "fragment"]
ClassificationCardinality = Literal["single", "multi"]


class ClassificationDatasetRequest(BaseModel):
    dataset_version_id: str = Field(min_length=1, max_length=36)
    mode: ClassificationMode = "multiclass"
    minimum_crop_size_px: int = Field(default=10, ge=1, le=4096)
    padding_fraction: float = Field(default=0.0, ge=0, le=1)


class ClassificationDatasetClassSummary(BaseModel):
    key: str
    label: str
    crop_count: int = Field(ge=0)


class ClassificationDatasetPreviewResponse(BaseModel):
    dataset_version_id: str
    mode: ClassificationMode
    minimum_crop_size_px: int
    eligible_crop_count: int
    removed_during_preprocessing_count: int
    missing_state_count: int
    split_counts: dict[str, int]
    classes: list[ClassificationDatasetClassSummary]
    warnings: list[str]


class ClassificationTrainingRequest(ClassificationDatasetRequest):
    run_name: str = Field(default="classification-run", min_length=1, max_length=200)
    architecture: str = Field(default="yolov8n-cls.yaml", min_length=1, max_length=200)
    initial_checkpoint_model_id: str | None = Field(default=None, max_length=36)
    epochs: int = Field(default=50, ge=1, le=10000)
    patience: int = Field(default=20, ge=0, le=10000)
    batch: int = Field(default=16, ge=1, le=1024)
    imgsz: int = Field(default=224, ge=32, le=4096)
    device: str = Field(default="auto", min_length=1, max_length=60)
    precision: Literal["fp32", "amp"] = "amp"
    random_seed: int | None = None
    notes: str | None = Field(default=None, max_length=5000)


class ClassificationInferenceRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=36)
    image_ids: list[str] = Field(min_length=1)
    minimum_crop_size_px: int = Field(default=10, ge=1, le=4096)
    padding_fraction: float = Field(default=0.0, ge=0, le=1)
    device: str = Field(default="auto", min_length=1, max_length=60)
    label_set: str = Field(
        default="default",
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )


class ClassificationPredictionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    image_id: str
    annotation_id: str | None
    model_id: str
    inference_job_id: str | None
    label_set: str
    classification_mode: str
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    predicted_label: str
    predicted_index: int | None
    label_class_id: str | None
    confidence: float
    probabilities_json: dict[str, float]
    review_status: str
    accepted_label_class_id: str | None
    inference_settings_json: dict[str, Any]
    provenance_json: dict[str, Any]
    created_at: datetime
    reviewed_at: datetime | None


class ClassificationPredictionPage(BaseModel):
    items: list[ClassificationPredictionResponse]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    pages: int = Field(ge=0)


class ClassificationReviewRequest(BaseModel):
    action: Literal["accept", "reject"]
    label_class_id: str | None = Field(default=None, max_length=36)

    @model_validator(mode="after")
    def reject_cannot_relabel(self) -> ClassificationReviewRequest:
        if self.action == "reject" and self.label_class_id is not None:
            raise ValueError("Rejected predictions cannot assign a class")
        return self


class ImageLabelWriteRequest(BaseModel):
    label_class_id: str = Field(min_length=1, max_length=36)
    label_set: str = Field(default="default", min_length=1, max_length=100)
    status: str = Field(default="verified", min_length=1, max_length=30)


class ImageLabelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    image_id: str
    label_class_id: str
    label_set: str
    confidence: float | None
    source_type: str
    status: str
    created_at: datetime


class ClassificationLabelSetCreateRequest(BaseModel):
    key: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    target_kind: ClassificationTargetKind = "annotation"
    cardinality: ClassificationCardinality = "single"
    allowed_class_ids: list[str] = Field(default_factory=list, max_length=1000)
    replaces_primary_class: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("allowed_class_ids")
    @classmethod
    def unique_allowed_classes(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("Allowed classification classes must be unique")
        return cleaned


class ClassificationLabelSetUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    cardinality: ClassificationCardinality | None = None
    allowed_class_ids: list[str] | None = Field(default=None, max_length=1000)
    replaces_primary_class: bool | None = None
    is_active: bool | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("allowed_class_ids")
    @classmethod
    def unique_updated_classes(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = [item.strip() for item in value if item.strip()]
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("Allowed classification classes must be unique")
        return cleaned


class ClassificationLabelSetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    key: str
    name: str
    description: str | None
    target_kind: str
    cardinality: str
    allowed_class_ids_json: list[str]
    replaces_primary_class: bool
    is_active: bool
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ClassificationAssignmentAcceptRequest(BaseModel):
    label_set_id: str | None = Field(default=None, max_length=36)
    label_class_id: str | None = Field(default=None, max_length=36)


class ClassificationAssignmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    label_set_id: str
    target_kind: str
    target_key: str
    image_id: str
    annotation_id: str | None
    mask_annotation_id: str | None
    fragment_key: str | None
    label_class_id: str
    source_type: str
    source_model_id: str | None
    source_prediction_id: str | None
    confidence: float | None
    probabilities_json: dict[str, float]
    status: str
    provenance_json: dict[str, Any]
    revision: int
    created_at: datetime
    updated_at: datetime
    reviewed_at: datetime | None


class ClassificationAssignmentPage(BaseModel):
    items: list[ClassificationAssignmentResponse]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    pages: int = Field(ge=0)


class ClassificationAssignmentExportRow(BaseModel):
    assignment_id: str
    image_id: str
    image_filename: str
    target_kind: str
    target_key: str
    annotation_id: str | None = None
    mask_annotation_id: str | None = None
    fragment_key: str | None = None
    bounding_box: list[float] | None = None
    mask_geometry_kind: str | None = None
    measurements: dict[str, Any] = Field(default_factory=dict)
    label_set_id: str
    label_set_key: str
    label_set_name: str
    cardinality: str
    label_class_id: str
    label_class_name: str
    source_model_id: str | None = None
    source_model_name: str | None = None
    source_prediction_id: str | None = None
    confidence: float | None = None
    probabilities: dict[str, float] = Field(default_factory=dict)
    status: str
    assignment_revision: int
    provenance: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    reviewed_at: datetime | None = None


class ClassificationAssignmentExportResponse(BaseModel):
    project_id: str
    row_count: int = Field(ge=0)
    rows: list[ClassificationAssignmentExportRow]
