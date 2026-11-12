"""API contracts for multi-animal pose identity tracking and evaluation."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PoseIdentityAssociationParameters(BaseModel):
    max_gap_frames: int = Field(default=5, ge=0, le=10_000)
    max_normalized_distance: float = Field(default=1.5, gt=0)
    minimum_iou: float = Field(default=0.0, ge=0, le=1)
    minimum_landmark_similarity: float = Field(default=0.0, ge=0, le=1)
    minimum_detection_confidence: float = Field(default=0.05, ge=0, le=1)
    acceptance_threshold: float = Field(default=0.75, gt=0)
    low_confidence_threshold: float = Field(default=0.6, ge=0, le=1)
    proximity_weight: float = Field(default=0.35, ge=0)
    overlap_weight: float = Field(default=0.2, ge=0)
    landmark_weight: float = Field(default=0.25, ge=0)
    motion_weight: float = Field(default=0.2, ge=0)
    confidence_weight: float = Field(default=0.1, ge=0)

    @model_validator(mode="after")
    def require_positive_weight(self) -> PoseIdentityAssociationParameters:
        if (
            self.proximity_weight
            + self.overlap_weight
            + self.landmark_weight
            + self.motion_weight
            + self.confidence_weight
            <= 0
        ):
            raise ValueError("At least one association weight must be positive")
        return self


class PoseIdentityAssociationCreateRequest(BaseModel):
    video_id: str
    source_track_ids: list[str] = Field(min_length=1)
    pose_schema_id: str
    pose_schema_revision: int = Field(ge=1)
    pose_schema_content_hash: str = Field(min_length=64, max_length=64)
    parameters: PoseIdentityAssociationParameters = Field(
        default_factory=PoseIdentityAssociationParameters
    )
    device: Literal["cpu", "cuda", "auto"] = "auto"


class PoseIdentityLandmark(BaseModel):
    landmark_id: str
    x: float | None = None
    y: float | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    visibility: Literal["visible", "occluded", "out_of_frame", "absent"] = "visible"


class PoseIdentityObservationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    observation_series_id: str
    revision: int
    supersedes_observation_id: str | None
    animal_identity_id: str | None
    source_video_track_id: str
    source_detection_key: str
    frame_index: int
    bbox_json: list[float]
    landmarks_json: list[dict[str, Any]]
    detection_confidence: float | None
    association_confidence: float | None
    visibility_state: str
    assignment_source: str
    verification_state: str
    coordinate_space: str
    is_current: bool


class PoseAnimalIdentityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    stable_identity_key: str
    display_name: str | None
    origin: str
    verification_state: str
    lifecycle_state: str
    first_frame: int
    last_frame: int | None
    mean_association_confidence: float | None
    revision: int


class PoseIdentityAssociationRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    video_id: str
    source_model_id: str | None
    source_job_id: str | None
    pose_schema_id: str
    pose_schema_revision: int
    pose_schema_content_hash: str
    algorithm: str
    algorithm_version: str
    parameters_json: dict[str, Any]
    parameters_sha256: str
    input_manifest_sha256: str
    source_coordinate_space: str
    source_width: int
    source_height: int
    status: str
    progress_json: dict[str, Any]
    error_json: dict[str, Any] | None
    revision: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class PoseIdentityCorrectionRequest(BaseModel):
    action: Literal["reassign", "split", "merge", "swap", "accept", "reject"]
    target_type: Literal["observation", "identity", "range"]
    target_id: str
    destination_identity_id: str | None = None
    frame_start: int | None = Field(default=None, ge=0)
    frame_end: int | None = Field(default=None, ge=0)
    reason: str | None = Field(default=None, max_length=4_000)
    actor: str = Field(default="local_user", min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_range_and_destination(self) -> PoseIdentityCorrectionRequest:
        if (
            self.frame_start is not None
            and self.frame_end is not None
            and self.frame_end < self.frame_start
        ):
            raise ValueError("frame_end must be greater than or equal to frame_start")
        if self.action in {"reassign", "merge", "swap"} and not self.destination_identity_id:
            raise ValueError(f"{self.action} requires destination_identity_id")
        return self


class PoseIdentityCorrectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    association_run_id: str
    revision: int
    action: str
    target_type: str
    target_id: str
    frame_start: int | None
    frame_end: int | None
    before_json: dict[str, Any]
    after_json: dict[str, Any]
    before_sha256: str
    after_sha256: str
    reason: str | None
    actor: str
    created_at: datetime


class PoseIdentityTruthDatasetCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    video_id: str
    pose_schema_id: str
    pose_schema_revision: int = Field(ge=1)
    pose_schema_content_hash: str = Field(min_length=64, max_length=64)
    observations: list[dict[str, Any]] = Field(min_length=1)
    verified_by: str = Field(min_length=1, max_length=100)
    verification_state: Literal["scientist_verified"] = "scientist_verified"


class PoseIdentityEvaluationRequest(BaseModel):
    truth_dataset_id: str
    spatial_iou_threshold: float = Field(default=0.5, ge=0, le=1)


class PoseIdentityEvaluationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    association_run_id: str
    association_run_revision: int
    truth_dataset_id: str
    configuration_json: dict[str, Any]
    metrics_json: dict[str, Any]
    warnings_json: list[str]
    provenance_json: dict[str, Any]
    result_sha256: str
    created_at: datetime
