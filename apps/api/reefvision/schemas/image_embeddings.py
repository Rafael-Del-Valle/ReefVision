"""Persisted visual embedding and active-learning diversity schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from reefvision.schemas.jobs import JobResponse


class ImageEmbeddingWriteRequest(BaseModel):
    embedding_model_id: str = Field(min_length=1, max_length=300)
    embedding_model_checksum: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
    )
    vector: list[FiniteFloat] = Field(min_length=2, max_length=8192)
    provider_id: str = Field(default="manual", min_length=1, max_length=100)
    model_version: str = Field(default="unknown", min_length=1, max_length=100)
    preprocessing_version: str = Field(default="manual-v1", min_length=1, max_length=100)
    source_image_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    source_kind: Literal["image", "crop"] = "image"
    crop: dict[str, float] | None = None
    normalization: Literal["l2"] = "l2"
    replace_existing: bool = True
    source: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def reject_zero_vector(self) -> ImageEmbeddingWriteRequest:
        if sum(float(value) ** 2 for value in self.vector) <= 0:
            raise ValueError("Embedding vectors cannot be all zero")
        return self


class ImageEmbeddingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    image_id: str
    embedding_model_id: str
    embedding_model_checksum: str | None
    embedding_key: str
    provider_id: str
    model_version: str
    preprocessing_version: str
    source_image_sha256: str | None
    source_kind: str
    crop_json: dict[str, Any] | None
    normalization: str
    status: str
    dimension: int
    vector_sha256: str
    source_json: dict[str, object]
    created_at: datetime
    updated_at: datetime


class EmbeddingCropRequest(BaseModel):
    image_id: str = Field(min_length=36, max_length=36)
    x_min: float = Field(ge=0)
    y_min: float = Field(ge=0)
    x_max: float = Field(gt=0)
    y_max: float = Field(gt=0)

    @model_validator(mode="after")
    def positive_area(self) -> EmbeddingCropRequest:
        if self.x_max <= self.x_min or self.y_max <= self.y_min:
            raise ValueError("Embedding crop must have positive width and height")
        return self


class ImageEmbeddingGenerateRequest(BaseModel):
    provider_id: Literal[
        "ultralytics_backbone",
        "color_texture_v1",
        "transformers_vision",
    ] = "ultralytics_backbone"
    model_id: str = Field(default="ultralytics/yolo11/detect/n", min_length=1, max_length=300)
    model_checksum: str | None = Field(default=None, min_length=64, max_length=64)
    device: str = Field(default="auto", min_length=1, max_length=60)
    local_files_only: bool = True
    image_ids: list[str] = Field(default_factory=list, max_length=100_000)
    replace_existing: bool = False
    batch_size: int = Field(default=8, ge=1, le=64)
    preprocessing_version: str | None = Field(default=None, max_length=100)
    crop_boxes: list[EmbeddingCropRequest] = Field(default_factory=list, max_length=100_000)

    @model_validator(mode="after")
    def unique_images(self) -> ImageEmbeddingGenerateRequest:
        if not self.local_files_only:
            raise ValueError(
                "Embedding inference cannot download weights; explicitly install and "
                "verify a local provider model first"
            )
        if len(self.image_ids) != len(set(self.image_ids)):
            raise ValueError("Embedding image IDs must be unique")
        crop_keys = [
            (item.image_id, item.x_min, item.y_min, item.x_max, item.y_max)
            for item in self.crop_boxes
        ]
        if len(crop_keys) != len(set(crop_keys)):
            raise ValueError("Embedding crop requests must be unique")
        return self


class ImageEmbeddingGenerationResponse(BaseModel):
    embedding_model_id: str
    requested_image_count: int
    job: JobResponse


class ImageEmbeddingCoverageResponse(BaseModel):
    project_id: str
    provider_id: str
    embedding_model_id: str
    embedding_model_checksum: str | None
    preprocessing_version: str
    total_image_count: int = Field(ge=0)
    ready_image_count: int = Field(ge=0)
    missing_image_count: int = Field(ge=0)
    stale_image_count: int = Field(ge=0)
    failed_image_count: int = Field(ge=0)
    missing_image_ids: list[str]
    stale_image_ids: list[str]
    dimension: int | None = Field(default=None, ge=2)
    warnings: list[str]


class EmbeddingDiversitySelectionRequest(BaseModel):
    embedding_model_id: str = Field(min_length=1, max_length=300)
    embedding_model_checksum: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
    )
    candidate_image_ids: list[str] = Field(default_factory=list)
    maximum_items: int = Field(default=100, ge=1, le=5000)
    diversity_weight: float = Field(default=0.7, ge=0, le=1)
    base_scores: dict[str, float] = Field(default_factory=dict)
    maximum_items_per_group: int | None = Field(default=None, ge=1, le=5000)

    @model_validator(mode="after")
    def unique_candidate_ids(self) -> EmbeddingDiversitySelectionRequest:
        if len(self.candidate_image_ids) != len(set(self.candidate_image_ids)):
            raise ValueError("Candidate image IDs must be unique")
        return self


class EmbeddingDiversitySelectionItem(BaseModel):
    image_id: str
    group_key: str | None
    rank: int = Field(ge=1)
    base_score: float
    normalized_base_score: float = Field(ge=0, le=1)
    novelty_score: float = Field(ge=0, le=1)
    selection_score: float
    nearest_selected_image_id: str | None
    vector_sha256: str


class EmbeddingDiversitySelectionResponse(BaseModel):
    project_id: str
    embedding_model_id: str
    embedding_model_checksum: str | None
    candidate_count: int = Field(ge=0)
    selected_count: int = Field(ge=0)
    skipped_missing_embedding_count: int = Field(ge=0)
    vector_dimension: int | None = Field(default=None, ge=2)
    diversity_weight: float = Field(ge=0, le=1)
    maximum_items_per_group: int | None
    selections: list[EmbeddingDiversitySelectionItem]
    warnings: list[str]
