"""Schemas for canonical temporal pose tracking, review, and export."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

PoseVisibilityState = Literal["visible", "occluded", "out_of_frame", "uncertain", "absent"]
PoseAssociationState = Literal["provisional", "confirmed", "unresolved", "identity_break"]
PoseVerificationState = Literal["unreviewed", "human_confirmed", "human_corrected"]
PoseObservationSource = Literal["model", "manual", "corrected", "import"]
PoseAssociationSource = Literal["tracker", "human", "import"]
PoseTrackLifecycleState = Literal["tentative", "confirmed", "terminated"]
PoseIdentityBreakReason = Literal[
    "ambiguous_crossing",
    "occlusion_gap_exceeded",
    "parent_track_break",
    "schema_change",
    "camera_cut",
    "manual_split",
    "algorithm_reset",
    "low_confidence",
    "out_of_frame_gap",
    "unknown",
]
PoseTemporalExportFormat = Literal["csv", "json"]


class PoseTemporalAssociationBuildRequest(BaseModel):
    max_gap_frames: int = Field(default=5, ge=0, le=10000)
    max_normalized_displacement: FiniteFloat = Field(default=0.35, gt=0, le=10)
    ambiguity_margin: FiniteFloat = Field(default=0.05, ge=0, le=1)
    confirm_after_observations: int = Field(default=3, ge=1, le=1000)
    replace_existing: bool = False


class PoseLandmarkTrackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    parent_video_track_id: str
    pose_schema_id: str
    pose_schema_revision: int
    semantic_label: str
    lifecycle_state: str
    first_frame: int
    last_frame: int | None
    origin: str
    source_model_id: str | None
    source_job_id: str | None
    association_algorithm: str | None
    association_algorithm_version: str | None
    association_parameters_json: dict[str, Any]
    association_parameters_hash: str | None
    created_at: datetime
    terminated_at: datetime | None


class PoseLandmarkObservationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    observation_series_id: str
    revision: int
    supersedes_observation_id: str | None
    parent_video_track_id: str
    frame_index: int
    time_s: float | None
    pose_schema_id: str
    pose_schema_revision: int
    semantic_label: str
    occurrence_index: int
    observed_x_px: float | None
    observed_y_px: float | None
    predicted_x_px: float | None
    predicted_y_px: float | None
    landmark_confidence: float | None
    visibility_state: str
    observation_source: str
    source_model_id: str | None
    source_job_id: str | None
    created_at: datetime


class PoseLandmarkAssociationDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    observation_id: str
    decision_revision: int
    supersedes_decision_id: str | None
    selected_landmark_track_id: str | None
    previous_observation_id: str | None
    association_state: str
    association_confidence: float | None
    verification_state: str
    association_source: str
    candidate_margin: float | None
    total_cost: float | None
    cost_breakdown_json: dict[str, Any] | None
    algorithm: str | None
    algorithm_version: str | None
    parameters_hash: str | None
    created_at: datetime


class PoseLandmarkAssociationCandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    association_decision_id: str
    candidate_landmark_track_id: str
    rank: int
    total_cost: float
    normalized_confidence: float | None
    motion_cost: float | None
    geometry_cost: float | None
    appearance_cost: float | None
    ordering_cost: float | None
    shape_cost: float | None


class PoseLandmarkIdentityBreakResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    parent_video_track_id: str
    predecessor_landmark_track_id: str
    successor_landmark_track_id: str | None
    break_after_frame: int
    successor_start_frame: int | None
    reason: str
    decision_confidence: float | None
    source: str
    human_verified: bool
    correction_id: str | None
    created_at: datetime


class PoseLandmarkCorrectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    parent_video_track_id: str
    action: str
    target_type: str
    target_id: str
    frame_start: int | None
    frame_end: int | None
    reason_code: str | None
    note: str | None
    before_json: dict[str, Any]
    after_json: dict[str, Any]
    actor: str
    created_at: datetime


class PoseTemporalTrackSummaryResponse(BaseModel):
    schema_version: Literal["pose-temporal-summary-0001"] = "pose-temporal-summary-0001"
    parent_video_track_id: str
    landmark_tracks: list[PoseLandmarkTrackResponse]
    observations: list[PoseLandmarkObservationResponse]
    association_decisions: list[PoseLandmarkAssociationDecisionResponse]
    association_candidates: list[PoseLandmarkAssociationCandidateResponse] = Field(
        default_factory=list
    )
    identity_breaks: list[PoseLandmarkIdentityBreakResponse]
    corrections: list[PoseLandmarkCorrectionResponse]


class PoseAssociationCorrectionRequest(BaseModel):
    selected_landmark_track_id: str | None = None
    association_state: PoseAssociationState
    reason_code: str = Field(min_length=1, max_length=100)
    note: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def validate_identity_state(self) -> PoseAssociationCorrectionRequest:
        if self.association_state in {"confirmed", "provisional"}:
            if self.selected_landmark_track_id is None:
                raise ValueError("Confirmed or provisional association requires a landmark track")
        elif self.selected_landmark_track_id is not None:
            raise ValueError("Unresolved or identity-break association must not select a track")
        return self


class PoseIdentityBreakCreateRequest(BaseModel):
    successor_landmark_track_id: str | None = None
    break_after_frame: int = Field(ge=0)
    successor_start_frame: int | None = Field(default=None, ge=0)
    reason: PoseIdentityBreakReason
    decision_confidence: FiniteFloat | None = Field(default=None, ge=0, le=1)
    note: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def validate_successor(self) -> PoseIdentityBreakCreateRequest:
        if self.successor_landmark_track_id is None and self.successor_start_frame is not None:
            raise ValueError("successor_start_frame requires a successor landmark track")
        if (
            self.successor_start_frame is not None
            and self.successor_start_frame <= self.break_after_frame
        ):
            raise ValueError("successor_start_frame must be after break_after_frame")
        return self


class PoseTemporalBuildResponse(BaseModel):
    schema_version: Literal["pose-temporal-build-0001"] = "pose-temporal-build-0001"
    parent_video_track_id: str
    created_landmark_tracks: int
    created_observations: int
    created_association_decisions: int
    unresolved_associations: int
    identity_breaks: int


class PoseTemporalQcIssue(BaseModel):
    code: Literal[
        "unresolved_identity",
        "low_association_confidence",
        "low_landmark_confidence",
        "high_motion_cost",
        "uncertain_visibility",
        "identity_break",
    ]
    frame_index: int = Field(ge=0)
    semantic_label: str
    occurrence_index: int | None = Field(default=None, ge=0)
    observation_id: str | None = None
    landmark_track_id: str | None = None
    value: float | None = None
    threshold: float | None = None
    message: str


class PoseTemporalQcResponse(BaseModel):
    schema_version: Literal["pose-temporal-qc-0001"] = "pose-temporal-qc-0001"
    parent_video_track_id: str
    issue_count: int
    flagged_frame_count: int
    unresolved_identity_count: int
    low_association_confidence_count: int
    low_landmark_confidence_count: int
    high_motion_cost_count: int
    uncertain_visibility_count: int
    identity_break_count: int
    issues: list[PoseTemporalQcIssue]


class PoseLandmarkTrackMetrics(BaseModel):
    landmark_track_id: str
    semantic_label: str
    first_frame: int
    last_frame: int
    duration_seconds: float
    associated_observation_count: int
    visible_observation_count: int
    occluded_observation_count: int
    out_of_frame_observation_count: int
    uncertain_observation_count: int
    absent_observation_count: int
    human_reviewed_observation_count: int
    path_length_pixels: float
    displacement_pixels: float
    mean_speed_pixels_per_second: float | None
    maximum_speed_pixels_per_second: float | None
    mean_association_confidence: float | None
    minimum_association_confidence: float | None
    identity_break_count: int


class PoseTemporalMetricsResponse(BaseModel):
    schema_version: Literal["pose-temporal-metrics-0001"] = "pose-temporal-metrics-0001"
    parent_video_track_id: str
    unit: Literal["pixels"] = "pixels"
    tracklets: list[PoseLandmarkTrackMetrics]
