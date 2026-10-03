"""Typed contracts for pose-specific active learning."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat

PoseActiveLearningSelectionUnit = Literal["frame", "clip"]
PoseActiveLearningReviewAction = Literal["start_review", "verify", "skip"]


class PoseActiveLearningScoreWeights(BaseModel):
    low_landmark_confidence: FiniteFloat = Field(default=0.30, ge=0, le=1)
    visibility_uncertainty: FiniteFloat = Field(default=0.15, ge=0, le=1)
    association_uncertainty: FiniteFloat = Field(default=0.20, ge=0, le=1)
    repeated_landmark_ambiguity: FiniteFloat = Field(default=0.15, ge=0, le=1)
    identity_break_signal: FiniteFloat = Field(default=0.15, ge=0, le=1)
    motion_anomaly: FiniteFloat = Field(default=0.05, ge=0, le=1)


class PoseActiveLearningRoundCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    video_id: str = Field(min_length=1, max_length=36)
    track_ids: list[str] = Field(default_factory=list, max_length=5000)
    model_ids: list[str] = Field(default_factory=list, max_length=20)
    selection_unit: PoseActiveLearningSelectionUnit = "frame"
    requested_size: int = Field(default=50, ge=1, le=1000)
    clip_radius_frames: int = Field(default=5, ge=0, le=10000)
    minimum_frame_spacing: int = Field(default=5, ge=0, le=10000)
    weights: PoseActiveLearningScoreWeights = Field(default_factory=PoseActiveLearningScoreWeights)
    created_by: str | None = Field(default=None, max_length=100)


class PoseActiveLearningRoundResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    video_id: str
    name: str
    status: str
    selection_unit: str
    requested_size: int
    selected_count: int
    clip_radius_frames: int
    minimum_frame_spacing: int
    model_ids_json: list[str]
    scoring_config_json: dict[str, Any]
    selection_manifest_json: dict[str, Any]
    selection_sha256: str
    created_by: str
    created_at: datetime
    completed_at: datetime | None


class PoseActiveLearningReviewTarget(BaseModel):
    workspace: Literal["pose_annotation_editor"] = "pose_annotation_editor"
    video_id: str
    video_track_id: str
    focus_frame: int
    frame_start: int
    frame_end: int
    pose_schema_id: str
    pose_schema_revision: int


class PoseActiveLearningCandidateResponse(BaseModel):
    id: str
    round_id: str
    video_track_id: str
    focus_frame: int
    frame_start: int
    frame_end: int
    acquisition_score: float
    score_components_json: dict[str, float]
    reason_codes_json: list[str]
    pose_schema_id: str
    pose_schema_revision: int
    source_track_revision: int
    source_model_ids_json: list[str]
    source_job_ids_json: list[str]
    provenance_json: dict[str, Any]
    provenance_sha256: str
    review_status: str
    review_started_track_revision: int | None
    verified_track_revision: int | None
    verified_pose_sha256: str | None
    correction_id: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    created_at: datetime
    review_target: PoseActiveLearningReviewTarget


class PoseActiveLearningReviewRequest(BaseModel):
    action: PoseActiveLearningReviewAction
    reviewed_by: str = Field(default="local_user", min_length=1, max_length=100)
    note: str | None = Field(default=None, max_length=5000)
    verified_track_revision: int | None = Field(default=None, ge=1)


class PoseActiveLearningExportManifestResponse(BaseModel):
    schema_version: Literal["pose-active-learning-retraining-manifest-0001"] = (
        "pose-active-learning-retraining-manifest-0001"
    )
    round_id: str
    project_id: str
    video_id: str
    selection_sha256: str
    selection_algorithm: str
    selection_algorithm_version: str
    status: str
    retraining_ready: bool
    verified_candidate_count: int
    pending_candidate_count: int
    skipped_candidate_count: int
    candidates: list[dict[str, Any]]
