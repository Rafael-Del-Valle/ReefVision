"""Managed video, sparse track, interpolation, analytics, and benchmark schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, FiniteFloat, field_validator, model_validator

from reefvision.geospatial.models import TelemetryMetadata

TrackInterpolation = Literal["linear", "hold"]
TrackGeometryKind = Literal["bbox"]


class VideoExtractRequest(BaseModel):
    every_n_frames: int = Field(default=1, ge=1, le=10000)


class AirDataAlignment(BaseModel):
    time_offset_s: FiniteFloat = 0.0
    evidence: str | None = None


class VideoAssetResponse(BaseModel):
    id: str
    project_id: str
    original_filename: str
    managed_path: str
    sha256: str
    media_type: str
    width_px: int
    height_px: int
    frame_count: int
    fps: float
    duration_seconds: float
    metadata_json: dict[str, Any]
    frame_directory_path: str | None
    extraction_job_id: str | None
    status: str
    revision: int
    created_at: datetime
    updated_at: datetime
    telemetry: TelemetryMetadata = Field(default_factory=TelemetryMetadata)
    airdata_telemetry: TelemetryMetadata = Field(default_factory=TelemetryMetadata)
    airdata_alignment: AirDataAlignment = Field(default_factory=AirDataAlignment)

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def telemetry_from_metadata(self) -> VideoAssetResponse:
        self.telemetry = TelemetryMetadata.model_validate(self.metadata_json.get("telemetry", {}))
        self.airdata_telemetry = TelemetryMetadata.model_validate(
            self.metadata_json.get("airdata_telemetry", {})
        )
        self.airdata_alignment = AirDataAlignment.model_validate(
            self.metadata_json.get("airdata_alignment", {})
        )
        return self


class VideoPoseObservation(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    semantic_label: str = Field(min_length=1, max_length=100)
    occurrence_index: int = Field(ge=0, le=999)
    x: FiniteFloat = Field(ge=0)
    y: FiniteFloat = Field(ge=0)
    confidence: FiniteFloat | None = Field(default=None, ge=0, le=1)
    status: Literal["visible", "occluded", "out_of_frame", "uncertain", "absent"] = "visible"
    source: Literal["model", "manual", "corrected"] = "model"


class VideoTrackKeyframe(BaseModel):
    frame: int = Field(ge=0)
    bbox: tuple[float, float, float, float]
    confidence: float | None = Field(default=None, ge=0, le=1)
    keypoints: list[tuple[FiniteFloat, FiniteFloat, FiniteFloat]] | None = Field(
        default=None,
        max_length=1000,
    )
    pose_observations: list[VideoPoseObservation] | None = Field(
        default=None,
        max_length=1000,
    )
    mask_polygons: list[list[tuple[FiniteFloat, FiniteFloat]]] | None = Field(
        default=None,
        max_length=30,
    )

    @field_validator("mask_polygons")
    @classmethod
    def validate_mask_polygons(
        cls, value: list[list[tuple[FiniteFloat, FiniteFloat]]] | None
    ) -> list[list[tuple[FiniteFloat, FiniteFloat]]] | None:
        if value is None:
            return None
        for polygon in value:
            if len(polygon) < 3 or len(polygon) > 20000:
                raise ValueError("Mask polygons require 3-20000 vertices")
            if any(x < 0 or y < 0 for x, y in polygon):
                raise ValueError("Mask polygon coordinates must be nonnegative")
        return value

    @field_validator("bbox")
    @classmethod
    def positive_box(
        cls,
        value: tuple[float, float, float, float],
    ) -> tuple[float, float, float, float]:
        x, y, width, height = value
        if x < 0 or y < 0 or width <= 0 or height <= 0:
            raise ValueError("Track boxes require nonnegative origins and positive dimensions")
        return value

    @field_validator("keypoints")
    @classmethod
    def valid_keypoints(
        cls,
        value: list[tuple[FiniteFloat, FiniteFloat, FiniteFloat]] | None,
    ) -> list[tuple[FiniteFloat, FiniteFloat, FiniteFloat]] | None:
        if value is None:
            return None
        for x, y, confidence in value:
            if x < 0 or y < 0:
                raise ValueError("Pose keypoint coordinates must be nonnegative")
            if confidence < 0 or confidence > 1:
                raise ValueError("Pose keypoint confidence must be between 0 and 1")
        return value


class VideoTrackCreate(BaseModel):
    label_class_id: str = Field(min_length=1, max_length=36)
    track_number: int | None = Field(default=None, ge=1)
    geometry_kind: TrackGeometryKind = "bbox"
    keyframes: list[VideoTrackKeyframe] = Field(min_length=1, max_length=100000)
    interpolation: TrackInterpolation = "linear"
    status: str = Field(default="verified", min_length=1, max_length=30)

    @model_validator(mode="after")
    def unique_ordered_frames(self) -> VideoTrackCreate:
        frames = [item.frame for item in self.keyframes]
        if frames != sorted(frames) or len(frames) != len(set(frames)):
            raise ValueError("Track keyframes must use unique frames in ascending order")
        return self


class VideoTrackUpdate(BaseModel):
    base_revision: int = Field(ge=1)
    label_class_id: str = Field(min_length=1, max_length=36)
    keyframes: list[VideoTrackKeyframe] = Field(min_length=1, max_length=100000)
    interpolation: TrackInterpolation = "linear"
    status: str = Field(default="verified", min_length=1, max_length=30)

    @model_validator(mode="after")
    def unique_ordered_frames(self) -> VideoTrackUpdate:
        frames = [item.frame for item in self.keyframes]
        if frames != sorted(frames) or len(frames) != len(set(frames)):
            raise ValueError("Track keyframes must use unique frames in ascending order")
        return self


class VideoTrackResponse(BaseModel):
    id: str
    video_id: str
    label_class_id: str
    track_number: int
    geometry_kind: str
    keyframes_json: list[dict[str, Any]]
    interpolation: str
    status: str
    source_model_id: str | None
    source_job_id: str | None
    metadata_json: dict[str, Any] | None
    revision: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InterpolatedTrackFrame(BaseModel):
    frame: int
    timestamp_seconds: float
    bbox: tuple[float, float, float, float]
    center_x: float
    center_y: float
    source: Literal["keyframe", "interpolated"]


class VideoTrackInterpolationResponse(BaseModel):
    track_id: str
    video_id: str
    interpolation: str
    frames: list[InterpolatedTrackFrame]


class VideoTrackAnalyticsResponse(BaseModel):
    track_id: str
    video_id: str
    track_number: int
    label_class_id: str
    first_frame: int
    last_frame: int
    observed_frame_count: int
    duration_seconds: float
    path_length_pixels: float
    mean_speed_pixels_per_second: float
    maximum_speed_pixels_per_second: float
    displacement_pixels: float
    mean_bbox_area_pixels: float
    occupancy_grid: dict[str, int]


class VideoFrameObjectMetric(BaseModel):
    track_id: str
    track_number: int
    label_class_id: str
    bbox: tuple[float, float, float, float]
    center_x: float
    center_y: float
    nearest_neighbor_track_id: str | None = None
    nearest_neighbor_distance_pixels: float | None = None
    nearest_neighbor_track_id_meters: str | None = None
    nearest_neighbor_distance_meters: float | None = None


class VideoFrameSpatialMetricsResponse(BaseModel):
    video_id: str
    frame_index: int
    object_count: int
    mean_nearest_neighbor_distance_pixels: float | None = None
    minimum_nearest_neighbor_distance_pixels: float | None = None
    mean_nearest_neighbor_distance_meters: float | None = None
    minimum_nearest_neighbor_distance_meters: float | None = None
    objects: list[VideoFrameObjectMetric]


class VideoTrackingCreateRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=36)
    tracking_mode: Literal["auto", "detect", "segment", "hybrid"] = "auto"
    segmentation_model_id: str | None = Field(default=None, min_length=1, max_length=36)
    hybrid_match_iou: float = Field(default=0.5, gt=0, le=1)
    tracker: str = Field(default="bytetrack.yaml", min_length=1, max_length=200)
    confidence: float = Field(default=0.25, ge=0, le=1)
    iou: float = Field(default=0.5, ge=0, le=1)
    device: str = Field(default="auto", min_length=1, max_length=60)
    minimum_track_frames: int = Field(default=2, ge=1, le=1000000)
    link_detections: bool = True

    @model_validator(mode="after")
    def validate_tracking_mode(self) -> VideoTrackingCreateRequest:
        if self.tracking_mode == "hybrid":
            if not self.segmentation_model_id:
                raise ValueError("Hybrid tracking requires a segmentation model")
            if self.segmentation_model_id == self.model_id:
                raise ValueError("Hybrid tracking requires two different models")
            if not self.link_detections:
                raise ValueError("Hybrid tracking requires linking across frames")
        elif self.segmentation_model_id is not None:
            raise ValueError("A secondary segmentation model is only valid in hybrid mode")
        return self


class AnnotatedVideoOverlayOptions(BaseModel):
    boxes: bool | None = None
    track_ids: bool | None = None
    class_labels: bool | None = None
    confidence: bool | None = None
    trails: bool | None = None
    frame_time: bool | None = None
    counters: bool | None = None


class AnnotatedVideoExportCreateRequest(BaseModel):
    source_tracking_job_id: str = Field(min_length=1, max_length=36)
    preset: Literal["clean_tracking", "full_review"] = "clean_tracking"
    overlays: AnnotatedVideoOverlayOptions = Field(default_factory=AnnotatedVideoOverlayOptions)
    trail_length: int = Field(default=60, ge=2, le=1000)


class VideoMetricDepth3DCreateRequest(BaseModel):
    track_ids: list[str] = Field(min_length=1, max_length=10000)
    device: str = Field(default="auto", min_length=1, max_length=60)
    input_size: int = Field(default=518, ge=196, le=1036)
    max_res: int = Field(default=1280, ge=256, le=8192)
    core_fraction: float = Field(default=0.6, gt=0, le=1)
    minimum_valid_fraction: float = Field(default=0.25, ge=0, le=1)
    maximum_frame_gap: int | None = Field(default=None, ge=1, le=100000)
    allow_model_download: bool = False
    allow_resolution_fallback: bool = True

    @model_validator(mode="after")
    def validate_scientific_3d_request(self) -> VideoMetricDepth3DCreateRequest:
        if len(set(self.track_ids)) != len(self.track_ids):
            raise ValueError("Scientific 3D track IDs must be unique")
        if self.input_size % 14 != 0:
            raise ValueError("Scientific 3D input_size must be a multiple of 14")
        return self


class VideoTrackingRunResponse(BaseModel):
    job_id: str
    project_id: str
    video_id: str
    status: str
    stage: str
    tracker: str
    model_id: str | None
    tracking_mode: Literal["auto", "detect", "segment", "hybrid"] = "auto"
    segmentation_model_id: str | None = None
    link_detections: bool
    confidence: float
    iou: float
    device: str
    minimum_track_frames: int
    progress_current: int
    progress_total: int
    track_count: int
    observation_count: int
    live_detection_count: int
    live_observation_count: int
    live_tracks_seen: int
    heartbeat_at: datetime | None
    stale: bool
    unmapped_labels: list[str]
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class VideoTrackingEvaluationRequest(BaseModel):
    ground_truth_track_ids: list[str] = Field(min_length=1, max_length=10000)
    prediction_track_ids: list[str] = Field(default_factory=list, max_length=10000)
    iou_threshold: float = Field(default=0.5, ge=0, le=1)
    class_aware: bool = True
    start_frame: int | None = Field(default=None, ge=0)
    end_frame: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_track_sets_and_range(self) -> VideoTrackingEvaluationRequest:
        if len(set(self.ground_truth_track_ids)) != len(self.ground_truth_track_ids):
            raise ValueError("Ground-truth track IDs must be unique")
        if len(set(self.prediction_track_ids)) != len(self.prediction_track_ids):
            raise ValueError("Prediction track IDs must be unique")
        if set(self.ground_truth_track_ids) & set(self.prediction_track_ids):
            raise ValueError("Ground-truth and prediction track IDs must not overlap")
        if (
            self.start_frame is not None
            and self.end_frame is not None
            and self.end_frame < self.start_frame
        ):
            raise ValueError("end_frame must be greater than or equal to start_frame")
        return self


class VideoTrackingEvaluationPerTrack(BaseModel):
    ground_truth_track_id: str
    ground_truth_track_number: int
    label_class_id: str
    ground_truth_observations: int
    matched_observations: int
    missed_observations: int
    recall: float
    id_switches: int
    fragmentations: int
    matched_prediction_track_ids: list[str]
    mean_iou: float | None
    mean_center_error_pixels: float | None


class VideoTrackingEvaluationResponse(BaseModel):
    schema_version: Literal["video-tracking-evaluation-0001"]
    video_id: str
    start_frame: int
    end_frame: int
    iou_threshold: float
    class_aware: bool
    matching_policy: Literal["temporal-continuity-then-greedy-iou"]
    ground_truth_track_ids: list[str]
    prediction_track_ids: list[str]
    ground_truth_track_count: int
    prediction_track_count: int
    ground_truth_observations: int
    prediction_observations: int
    matched_observations: int
    missed_observations: int
    false_positive_observations: int
    recall: float
    precision: float
    missed_tracks: int
    false_positive_tracks: int
    false_positive_prediction_track_ids: list[str]
    id_switches: int
    fragmentations: int
    mean_iou: float | None
    mean_center_error_pixels: float | None
    mota: float
    per_track: list[VideoTrackingEvaluationPerTrack]


class VideoTrackingBenchmarkCandidate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    prediction_track_ids: list[str] = Field(default_factory=list, max_length=10000)
    source_job_id: str | None = Field(default=None, min_length=1, max_length=36)

    @model_validator(mode="after")
    def validate_selector(self) -> VideoTrackingBenchmarkCandidate:
        if len(set(self.prediction_track_ids)) != len(self.prediction_track_ids):
            raise ValueError("Candidate prediction track IDs must be unique")
        has_tracks = bool(self.prediction_track_ids)
        has_job = self.source_job_id is not None
        if has_tracks == has_job:
            raise ValueError(
                "Candidate requires exactly one of prediction_track_ids or source_job_id"
            )
        return self


class VideoTrackingBenchmarkRequest(BaseModel):
    ground_truth_track_ids: list[str] = Field(min_length=1, max_length=10000)
    candidates: list[VideoTrackingBenchmarkCandidate] = Field(min_length=2, max_length=20)
    iou_threshold: float = Field(default=0.5, ge=0, le=1)
    class_aware: bool = True
    start_frame: int | None = Field(default=None, ge=0)
    end_frame: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_benchmark(self) -> VideoTrackingBenchmarkRequest:
        if len(set(self.ground_truth_track_ids)) != len(self.ground_truth_track_ids):
            raise ValueError("Ground-truth track IDs must be unique")
        normalized_names = [candidate.name.strip().casefold() for candidate in self.candidates]
        if len(set(normalized_names)) != len(normalized_names):
            raise ValueError("Benchmark candidate names must be unique")
        truth_ids = set(self.ground_truth_track_ids)
        if any(truth_ids & set(candidate.prediction_track_ids) for candidate in self.candidates):
            raise ValueError("Ground-truth and candidate prediction track IDs must not overlap")
        if (
            self.start_frame is not None
            and self.end_frame is not None
            and self.end_frame < self.start_frame
        ):
            raise ValueError("end_frame must be greater than or equal to start_frame")
        return self


class VideoTrackingBenchmarkResult(BaseModel):
    rank: int = Field(ge=1)
    name: str
    source_job_id: str | None
    prediction_track_ids: list[str]
    tracker: str | None
    model_id: str | None
    job_status: str | None
    tracking_settings: dict[str, Any]
    evaluation: VideoTrackingEvaluationResponse


class VideoTrackingBenchmarkResponse(BaseModel):
    schema_version: Literal["video-tracking-benchmark-0001"]
    video_id: str
    winner: str
    ground_truth_track_ids: list[str]
    start_frame: int
    end_frame: int
    iou_threshold: float
    class_aware: bool
    results: list[VideoTrackingBenchmarkResult]


class Scientific3DCalibrationReferenceSample(BaseModel):
    track_id: str = Field(min_length=1, max_length=100)
    frame: int = Field(ge=0)
    expected_depth_m: FiniteFloat = Field(gt=0)


class Scientific3DCalibrationValidationRequest(BaseModel):
    reference_source: str = Field(min_length=3, max_length=300)
    reference_method: str = Field(min_length=3, max_length=120)
    setup_description: str = Field(min_length=3, max_length=1000)
    reference_samples: list[Scientific3DCalibrationReferenceSample] = Field(
        min_length=5,
        max_length=5000,
    )
    relative_tolerance: FiniteFloat = Field(default=0.05, ge=0, le=0.10)
    absolute_tolerance_m: FiniteFloat = Field(default=0.02, ge=0, le=0.05)
    independent_reference_confirmed: Literal[True]
    same_optical_setup_confirmed: Literal[True]
    underwater_environment_confirmed: Literal[True]
    notes: str | None = Field(default=None, max_length=2000)
