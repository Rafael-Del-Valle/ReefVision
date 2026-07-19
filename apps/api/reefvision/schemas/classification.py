"""Classification dataset, training, inference, and review schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ClassificationMode = Literal["multiclass", "binary_state"]
ClassificationReviewStatus = Literal["pending", "accepted", "rejected"]


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
    label_set: str = Field(default="default", min_length=1, max_length=100)


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
