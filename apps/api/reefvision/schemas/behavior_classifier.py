"""Behavior-model training, inference, review, and export schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

BehaviorFeaturePreset = Literal[
    "track_only",
    "track_pose_geometry",
    "track_pose_identity",
]
BehaviorPredictionReviewAction = Literal[
    "accept",
    "edit_and_accept",
    "reject",
]
BehaviorExportFormat = Literal[
    "json",
    "bouts_csv",
    "predictions_csv",
]


class BehaviorModelTrainRequest(BaseModel):
    ethogram_revision_id: str = Field(min_length=1, max_length=36)
    channel: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=200)
    feature_preset: BehaviorFeaturePreset = "track_only"
    track_ids: list[str] = Field(default_factory=list, max_length=10000)


class BehaviorModelResponse(BaseModel):
    id: str
    project_id: str
    ethogram_revision_id: str
    channel: str
    display_name: str
    algorithm: str
    algorithm_version: str
    feature_set_version: str
    feature_preset: str
    feature_names: list[str]
    feature_request: dict[str, Any]
    scaler: dict[str, Any]
    centroids: dict[str, Any]
    class_counts: dict[str, int]
    training_track_ids: list[str]
    training_bout_ids: list[str]
    training_sample_count: int
    training_manifest_sha256: str
    created_by: str
    created_at: datetime


class BehaviorPredictionRunRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=36)
    window_frames: int = Field(default=30, ge=1, le=100000)
    stride_frames: int = Field(default=30, ge=1, le=100000)
    start_frame: int | None = Field(default=None, ge=0)
    end_frame: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_range(self) -> BehaviorPredictionRunRequest:
        if (
            self.start_frame is not None
            and self.end_frame is not None
            and self.end_frame < self.start_frame
        ):
            raise ValueError("end_frame must be greater than or equal to start_frame")
        return self


class BehaviorPredictionResponse(BaseModel):
    id: str
    video_track_id: str
    model_id: str
    ethogram_revision_id: str
    behavior_state_id: str
    behavior_code: str
    behavior_label: str
    channel: str
    start_frame: int
    end_frame: int
    prediction_score: float = Field(ge=0, le=1)
    score_semantics: Literal["normalized_inverse_distance_not_calibrated"] = (
        "normalized_inverse_distance_not_calibrated"
    )
    scores: dict[str, Any]
    feature_vector: dict[str, float]
    feature_parameters_sha256: str
    source_track_revision: int
    stale_against_track: bool
    review_status: str
    accepted_bout_series_id: str | None
    reviewed_at: datetime | None
    reviewed_by: str | None
    created_at: datetime


class BehaviorPredictionReviewRequest(BaseModel):
    action: BehaviorPredictionReviewAction
    behavior_state_id: str | None = Field(default=None, max_length=36)
    start_frame: int | None = Field(default=None, ge=0)
    end_frame: int | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def validate_edit(self) -> BehaviorPredictionReviewRequest:
        if (
            self.start_frame is not None
            and self.end_frame is not None
            and self.end_frame < self.start_frame
        ):
            raise ValueError("end_frame must be greater than or equal to start_frame")
        return self


class BehaviorPredictionRunResponse(BaseModel):
    track_id: str
    model_id: str
    source_track_revision: int
    prediction_count: int = Field(ge=0)
    predictions: list[BehaviorPredictionResponse]
