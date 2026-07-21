"""Tracker-independent evaluation and parameter-comparison schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field, FiniteFloat, model_validator


class TrackingBox(BaseModel):
    frame_index: int = Field(ge=0)
    track_id: str = Field(min_length=1, max_length=200)
    x: FiniteFloat
    y: FiniteFloat
    width: FiniteFloat = Field(gt=0)
    height: FiniteFloat = Field(gt=0)
    confidence: FiniteFloat | None = Field(default=None, ge=0, le=1)
    depth: FiniteFloat | None = None


class TrackingCandidate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    parameters: dict[str, object] = Field(default_factory=dict)
    boxes: list[TrackingBox] = Field(default_factory=list)


class TrackingEvaluationRequest(BaseModel):
    references: list[TrackingBox]
    candidates: list[TrackingCandidate] = Field(min_length=1, max_length=1000)
    minimum_iou: FiniteFloat = Field(default=0.5, ge=0, le=1)
    maximum_depth_gap: FiniteFloat | None = Field(default=None, ge=0)
    mostly_tracked_threshold: FiniteFloat = Field(default=0.8, ge=0, le=1)
    mostly_lost_threshold: FiniteFloat = Field(default=0.2, ge=0, le=1)

    @model_validator(mode="after")
    def validate_thresholds(self) -> TrackingEvaluationRequest:
        if self.mostly_lost_threshold > self.mostly_tracked_threshold:
            raise ValueError("Mostly-lost threshold cannot exceed mostly-tracked threshold")
        names = [candidate.name.casefold() for candidate in self.candidates]
        if len(names) != len(set(names)):
            raise ValueError("Tracking candidate names must be unique")
        return self


class TrackingFrameMatch(BaseModel):
    frame_index: int = Field(ge=0)
    reference_track_id: str
    predicted_track_id: str
    iou: float = Field(ge=0, le=1)
    center_error: float = Field(ge=0)
    depth_error: float | None = Field(default=None, ge=0)


class TrackingFrameSummary(BaseModel):
    frame_index: int = Field(ge=0)
    reference_count: int = Field(ge=0)
    predicted_count: int = Field(ge=0)
    matched_count: int = Field(ge=0)
    false_positive_count: int = Field(ge=0)
    false_negative_count: int = Field(ge=0)
    identity_switch_count: int = Field(ge=0)
    mean_iou: float | None = Field(default=None, ge=0, le=1)


class TrackingTrackSummary(BaseModel):
    reference_track_id: str
    reference_observation_count: int = Field(ge=0)
    matched_observation_count: int = Field(ge=0)
    coverage: float = Field(ge=0, le=1)
    fragmentation_count: int = Field(ge=0)
    identity_switch_count: int = Field(ge=0)
    matched_prediction_track_ids: list[str]
    mostly_tracked: bool
    mostly_lost: bool


class TrackingMetricSummary(BaseModel):
    candidate_name: str
    parameters: dict[str, object]
    reference_detection_count: int = Field(ge=0)
    predicted_detection_count: int = Field(ge=0)
    matched_detection_count: int = Field(ge=0)
    false_positive_count: int = Field(ge=0)
    false_negative_count: int = Field(ge=0)
    false_positive_track_count: int = Field(ge=0)
    false_negative_track_count: int = Field(ge=0)
    identity_switch_count: int = Field(ge=0)
    fragmentation_count: int = Field(ge=0)
    mostly_tracked_count: int = Field(ge=0)
    mostly_lost_count: int = Field(ge=0)
    mota: float
    motp: float = Field(ge=0, le=1)
    localization_iou: float = Field(ge=0, le=1)
    detection_precision: float = Field(ge=0, le=1)
    detection_recall: float = Field(ge=0, le=1)
    id_precision: float = Field(ge=0, le=1)
    id_recall: float = Field(ge=0, le=1)
    idf1: float = Field(ge=0, le=1)
    detection_accuracy: float = Field(ge=0, le=1)
    association_accuracy: float = Field(ge=0, le=1)
    hota: float = Field(ge=0, le=1)
    mean_center_error: float | None = Field(default=None, ge=0)
    mean_depth_error: float | None = Field(default=None, ge=0)
    mean_track_lifespan_frames: float | None = Field(default=None, ge=0)
    mean_track_continuity: float | None = Field(default=None, ge=0, le=1)
    matches: list[TrackingFrameMatch]
    per_frame: list[TrackingFrameSummary]
    per_track: list[TrackingTrackSummary]


class TrackingEvaluationResponse(BaseModel):
    minimum_iou: float = Field(ge=0, le=1)
    maximum_depth_gap: float | None = Field(default=None, ge=0)
    ranked_by_hota: list[TrackingMetricSummary]
    best_candidate_name: str
    warnings: list[str]


class VideoTrackingEvaluationCreateRequest(BaseModel):
    candidate_job_ids: list[str] = Field(default_factory=list, max_length=1000)
    confidence_thresholds: list[FiniteFloat] = Field(default_factory=list, max_length=100)
    minimum_iou: FiniteFloat = Field(default=0.5, ge=0, le=1)
    mostly_tracked_threshold: FiniteFloat = Field(default=0.8, ge=0, le=1)
    mostly_lost_threshold: FiniteFloat = Field(default=0.2, ge=0, le=1)
    include_archived_candidates: bool = True

    @model_validator(mode="after")
    def validate_comparison(self) -> VideoTrackingEvaluationCreateRequest:
        if self.mostly_lost_threshold > self.mostly_tracked_threshold:
            raise ValueError("Mostly-lost threshold cannot exceed mostly-tracked threshold")
        thresholds = [float(value) for value in self.confidence_thresholds]
        if any(value < 0 or value > 1 for value in thresholds):
            raise ValueError("Confidence thresholds must lie between zero and one")
        if len(thresholds) != len(set(thresholds)):
            raise ValueError("Confidence thresholds must be unique")
        if len(self.candidate_job_ids) != len(set(self.candidate_job_ids)):
            raise ValueError("Candidate job IDs must be unique")
        return self


class VideoTrackingEvaluationRunResponse(BaseModel):
    evaluation_id: str
    video_id: str
    ground_truth_available: bool
    minimum_iou: float = Field(ge=0, le=1)
    ranked_by_hota: list[TrackingMetricSummary]
    best_candidate_name: str | None
    configuration: dict[str, object]
    source_track_revisions: list[dict[str, object]]
    evaluation_sha256: str
    warnings: list[str]
