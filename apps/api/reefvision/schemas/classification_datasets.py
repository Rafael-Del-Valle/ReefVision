"""Immutable whole-image, mask, and fragment classification dataset schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ClassificationDatasetRatios(BaseModel):
    train: float = Field(default=0.7, ge=0, le=1)
    validation: float = Field(default=0.2, ge=0, le=1)
    test: float = Field(default=0.1, ge=0, le=1)

    @model_validator(mode="after")
    def positive_total(self) -> ClassificationDatasetRatios:
        if self.train + self.validation + self.test <= 0:
            raise ValueError("At least one classification dataset split ratio must be positive")
        return self


class ClassificationDatasetCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    label_set_id: str = Field(min_length=1, max_length=36)
    notes: str | None = Field(default=None, max_length=5000)
    split_seed: int = 42
    ratios: ClassificationDatasetRatios = Field(default_factory=ClassificationDatasetRatios)
    require_verified_masks: bool = True
    created_by: str = Field(default="local_user", min_length=1, max_length=100)


class ClassificationDatasetSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    label_set_id: str
    name: str
    notes: str | None
    status: str
    target_kind: str
    cardinality: str
    split_seed: int
    requested_ratios_json: dict[str, float]
    achieved_ratios_json: dict[str, float]
    class_map_json: list[dict[str, Any]]
    manifest_sha256: str
    sample_count: int
    target_count: int
    class_count: int
    warnings_json: list[str]
    created_by: str
    created_at: datetime
    completed_at: datetime


class ClassificationDatasetSampleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    snapshot_id: str
    target_kind: str
    target_key: str
    image_id: str
    mask_annotation_id: str | None
    fragment_key: str | None
    split: str
    group_key: str
    label_class_ids_json: list[str]
    assignment_ids_json: list[str]
    assignment_revisions_json: dict[str, int]
    source_image_sha256: str
    source_image_managed_path: str
    source_image_width_px: int
    source_image_height_px: int
    target_revision: int | None
    target_checksum: str
    geometry_json: dict[str, Any]
    provenance_json: dict[str, Any]
    sample_sha256: str
    created_at: datetime


class ClassificationDatasetDetailResponse(BaseModel):
    snapshot: ClassificationDatasetSnapshotResponse
    manifest: dict[str, Any]
    samples: list[ClassificationDatasetSampleResponse]
