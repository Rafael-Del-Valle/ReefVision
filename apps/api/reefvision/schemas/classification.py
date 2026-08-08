"""Image and crop classification workflow schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

ClassificationDatasetMode = Literal["image", "box_crop", "mask_crop"]
ClassificationReviewAction = Literal["accept", "reject"]


class ImageLabelSetRequest(BaseModel):
    label_set: str = Field(default="default", min_length=1, max_length=100)
    label_class_ids: list[str] = Field(default_factory=list, max_length=500)

    @field_validator("label_set")
    @classmethod
    def normalize_label_set(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("label_set cannot be blank")
        return normalized

    @field_validator("label_class_ids")
    @classmethod
    def unique_classes(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Classification label classes must be unique")
        return value


class ImageLabelResponse(BaseModel):
    id: str
    image_id: str
    label_class_id: str
    label_set: str
    confidence: float | None
    source_type: str
    source_model_id: str | None
    source_prediction_id: str | None
    provenance_json: dict[str, Any] | None
    status: str
    created_by: str
    revision: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ClassificationDatasetCreateRequest(BaseModel):
    dataset_version_id: str = Field(min_length=1, max_length=36)
    mode: ClassificationDatasetMode = "image"
    label_set: str = Field(default="default", min_length=1, max_length=100)
    minimum_crop_pixels: int = Field(default=16, ge=1, le=4096)


class ClassificationDatasetResponse(BaseModel):
    id: str
    project_id: str
    dataset_version_id: str
    mode: str
    label_set: str
    status: str
    manifest_json: dict[str, Any]
    manifest_sha256: str
    output_path: str
    archive_path: str
    sample_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ClassificationTrainingCreateRequest(BaseModel):
    classification_dataset_id: str = Field(min_length=1, max_length=36)
    architecture: str = Field(default="yolo11n-cls.pt", min_length=1, max_length=200)
    run_name: str = Field(default="classification", min_length=1, max_length=200)
    epochs: int = Field(default=50, ge=1, le=10000)
    image_size: int = Field(default=224, ge=32, le=4096)
    batch: int = Field(default=16, ge=1, le=1024)
    device: str = Field(default="auto", min_length=1, max_length=60)


class ClassificationInferenceCreateRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=36)
    image_ids: list[str] = Field(min_length=1, max_length=10000)
    label_set: str = Field(default="default", min_length=1, max_length=100)
    top_k: int = Field(default=5, ge=1, le=100)
    device: str = Field(default="auto", min_length=1, max_length=60)


class ClassificationPredictionResponse(BaseModel):
    id: str
    project_id: str
    image_id: str
    model_id: str
    label_class_id: str
    label_set: str
    confidence: float
    rank: int
    scores_json: dict[str, Any]
    status: str
    accepted_image_label_id: str | None
    created_at: datetime
    reviewed_at: datetime | None
    reviewed_by: str | None

    model_config = {"from_attributes": True}


class ClassificationPredictionReviewRequest(BaseModel):
    action: ClassificationReviewAction
    label_class_id: str | None = Field(default=None, max_length=36)
