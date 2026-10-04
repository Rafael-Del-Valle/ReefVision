"""Contracts for immutable pose-training datasets."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class PoseTrainingDatasetCreateRequest(BaseModel):
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
    )
    created_by: str = Field(
        default="local_user",
        min_length=1,
        max_length=100,
    )


class PoseTrainingDatasetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    source_round_id: str
    name: str
    status: str
    schema_version: str
    pose_schema_id: str
    pose_schema_revision: int
    pose_schema_content_hash: str
    source_selection_sha256: str
    source_retraining_manifest_sha256: str
    manifest_json: dict[str, Any]
    manifest_sha256: str
    item_count: int
    created_by: str
    created_at: datetime


class PoseTrainingDatasetItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    dataset_id: str
    candidate_id: str
    video_id: str
    video_sha256: str
    video_revision: int
    video_track_id: str
    label_class_id: str
    frame_index: int
    verified_track_revision: int
    pose_schema_id: str
    pose_schema_revision: int
    pose_schema_content_hash: str
    verified_pose_sha256: str
    canonical_pose_json: dict[str, Any]
    source_models_json: list[dict[str, Any]]
    source_job_ids_json: list[str]
    acquisition_provenance_json: dict[str, Any]
    review_provenance_json: dict[str, Any]
    item_sha256: str
    created_at: datetime


class PoseTrainingDatasetManifestResponse(BaseModel):
    schema_version: Literal["pose-training-dataset-manifest-0001"] = (
        "pose-training-dataset-manifest-0001"
    )

    dataset_id: str
    manifest_sha256: str
    manifest_json: dict[str, Any]
