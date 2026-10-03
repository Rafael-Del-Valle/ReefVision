"""Reproducible track- and pose-derived behavior feature vectors."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, FiniteFloat, model_validator

BehaviorFeatureSource = Literal[
    "track_kinematics",
    "pose_geometry",
    "pose_identity",
]
BehaviorPoseIdentityStatus = Literal["not_built", "current", "stale"]


class BehaviorFeatureRequest(BaseModel):
    start_frame: int | None = Field(default=None, ge=0)
    end_frame: int | None = Field(default=None, ge=0)
    include_predicted: bool = False
    include_uncertain: bool = True
    minimum_landmark_confidence: FiniteFloat | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_range(self) -> BehaviorFeatureRequest:
        if (
            self.start_frame is not None
            and self.end_frame is not None
            and self.end_frame < self.start_frame
        ):
            raise ValueError("end_frame must be greater than or equal to start_frame")
        return self


class BehaviorFeatureValue(BaseModel):
    name: str
    value: float | None
    unit: str
    source: BehaviorFeatureSource
    available: bool
    definition: str
    missing_reason: str | None = None

    @model_validator(mode="after")
    def validate_availability(self) -> BehaviorFeatureValue:
        if self.available and self.value is None:
            raise ValueError("Available behavior features require a numeric value")
        if not self.available and self.value is not None:
            raise ValueError("Unavailable behavior features must use value=null")
        if self.available and self.missing_reason is not None:
            raise ValueError("Available behavior features must not have a missing reason")
        if not self.available and not self.missing_reason:
            raise ValueError("Unavailable behavior features require a missing reason")
        return self


class BehaviorFeatureQuality(BaseModel):
    evaluated_frame_count: int = Field(ge=1)
    track_motion_interval_count: int = Field(ge=0)
    pose_sampled_frame_count: int = Field(ge=0)
    pose_spatial_sample_count: int = Field(ge=0)
    pose_observed_sample_count: int = Field(ge=0)
    pose_predicted_sample_count: int = Field(ge=0)
    pose_excluded_missing_coordinate_count: int = Field(ge=0)
    pose_excluded_filter_count: int = Field(ge=0)
    pose_resolved_identity_sample_count: int = Field(ge=0)
    pose_unresolved_identity_sample_count: int = Field(ge=0)
    pose_identity_movement_segment_count: int = Field(ge=0)
    pose_identity_continuity_segment_count: int = Field(ge=0)


class BehaviorFeatureVectorResponse(BaseModel):
    schema_version: Literal["behavior-feature-vector-0001"] = "behavior-feature-vector-0001"
    feature_set_version: Literal["reefvision-behavior-features-0001"] = (
        "reefvision-behavior-features-0001"
    )
    track_id: str
    video_id: str
    track_number: int
    source_track_revision: int = Field(ge=1)
    start_frame: int = Field(ge=0)
    end_frame: int = Field(ge=0)
    fps: float = Field(gt=0)
    evaluated_seconds_inclusive: float = Field(gt=0)
    coordinate_space: Literal["source_pixels"] = "source_pixels"
    track_sampling_policy: Literal["configured_track_interpolation"] = (
        "configured_track_interpolation"
    )
    pose_sampling_policy: Literal["persisted_canonical_pose_keyframes"] = (
        "persisted_canonical_pose_keyframes"
    )
    predicted_coordinate_policy: Literal[
        "exclude_occluded_predictions",
        "include_occluded_predictions",
    ]
    pose_identity_status: BehaviorPoseIdentityStatus
    pose_identity_warning: str | None
    parameters_sha256: str
    quality: BehaviorFeatureQuality
    features: list[BehaviorFeatureValue]
