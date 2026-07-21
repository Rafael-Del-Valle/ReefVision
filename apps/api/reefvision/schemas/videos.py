"""Video import, tracking, analytics, and export schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

VideoTrackerKind = Literal["bytetrack", "botsort"]
VideoTrackInterpolation = Literal["linear", "hold"]


class VideoAssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
    created_at: datetime
    updated_at: datetime
    revision: int = Field(ge=1)


class VideoImportResponse(BaseModel):
    video: VideoAssetResponse
    duplicate: bool = False


class VideoCalibrationUpdate(BaseModel):
    distance_per_pixel: float = Field(gt=0)
    unit: str = Field(default="cm", min_length=1, max_length=32)
    source: str = Field(default="manual", min_length=1, max_length=100)
    notes: str | None = Field(default=None, max_length=1000)


class VideoTrackKeyframe(BaseModel):
    id: str | None = Field(default=None, min_length=1, max_length=36)
    frame_index: int = Field(ge=0)
    timestamp_seconds: FiniteFloat | None = Field(default=None, ge=0)
    x_min: FiniteFloat = Field(ge=0)
    y_min: FiniteFloat = Field(ge=0)
    x_max: FiniteFloat = Field(gt=0)
    y_max: FiniteFloat = Field(gt=0)
    centroid_x: FiniteFloat | None = Field(default=None, ge=0)
    centroid_y: FiniteFloat | None = Field(default=None, ge=0)
    confidence: FiniteFloat | None = Field(default=None, ge=0, le=1)
    source: str = Field(default="human", min_length=1, max_length=50)
    manual_edit: bool = False
    automated_provenance: dict[str, Any] | None = None
    deleted_at: datetime | None = None
    revision: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def validate_box(self) -> VideoTrackKeyframe:
        if self.x_max <= self.x_min or self.y_max <= self.y_min:
            raise ValueError("Video track boxes must have positive width and height")
        self.centroid_x = (float(self.x_min) + float(self.x_max)) / 2.0
        self.centroid_y = (float(self.y_min) + float(self.y_max)) / 2.0
        return self


class VideoExtractJobRequest(BaseModel):
    video_path: str = Field(min_length=1)
    frames_path: str = Field(min_length=1)
    every_n_frames: int = Field(default=1, ge=1)


class VideoTrackCreateRequest(BaseModel):
    video_id: str = Field(min_length=1, max_length=36)
    operation_id: str | None = Field(default=None, min_length=1, max_length=100)
    actor: str = Field(default="local_user", min_length=1, max_length=100)
    label_class_id: str | None = Field(default=None, max_length=36)
    track_number: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    geometry_kind: str = Field(default="bounding_box", min_length=1, max_length=30)
    keyframes: list[VideoTrackKeyframe] = Field(min_length=1)
    interpolation: VideoTrackInterpolation = "linear"
    status: str = Field(default="verified", min_length=1, max_length=30)
    is_ground_truth: bool = False

    @model_validator(mode="after")
    def unique_frames(self) -> VideoTrackCreateRequest:
        frames = [item.frame_index for item in self.keyframes if item.deleted_at is None]
        if len(set(frames)) != len(frames):
            raise ValueError("Track keyframes must use unique frame indices")
        if self.is_ground_truth and self.status != "verified":
            raise ValueError("Ground-truth tracks must have verified status")
        return self


class VideoTrackUpdateRequest(BaseModel):
    operation_id: str | None = Field(default=None, min_length=1, max_length=100)
    expected_revision: int | None = Field(default=None, ge=1)
    actor: str = Field(default="local_user", min_length=1, max_length=100)
    label_class_id: str | None = Field(default=None, max_length=36)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    keyframes: list[VideoTrackKeyframe] | None = None
    interpolation: VideoTrackInterpolation | None = None
    status: str | None = Field(default=None, max_length=30)
    is_ground_truth: bool | None = None

    @model_validator(mode="after")
    def unique_frames(self) -> VideoTrackUpdateRequest:
        if self.keyframes is not None:
            frames = [item.frame_index for item in self.keyframes if item.deleted_at is None]
            if len(frames) != len(set(frames)):
                raise ValueError("Track keyframes must use unique frame indices")
        return self


class VideoTrackResponse(BaseModel):
    id: str
    video_id: str
    label_class_id: str | None
    origin_job_id: str | None
    track_number: int
    name: str | None
    geometry_kind: str
    keyframes: list[VideoTrackKeyframe]
    interpolation: str
    status: str
    source_type: str
    is_ground_truth: bool
    metadata_json: dict[str, Any]
    created_by: str
    updated_by: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    revision: int = Field(ge=1)


class VideoTrackingJobRequest(BaseModel):
    request_id: str | None = Field(default=None, min_length=1, max_length=100)
    model_id: str = Field(min_length=1, max_length=36)
    tracker: VideoTrackerKind = "bytetrack"
    device: Literal["auto", "cpu", "cuda"] = "auto"
    confidence_threshold: float = Field(default=0.25, ge=0, le=1)
    iou_threshold: float = Field(default=0.45, ge=0, le=1)
    every_n_frames: int = Field(default=1, ge=1, le=1000)
    replace_generated_tracks: bool = True
    tracker_options: dict[str, bool | int | float | str] = Field(default_factory=dict)
    force_new_run: bool = False

    @model_validator(mode="after")
    def validate_tracker_options(self) -> VideoTrackingJobRequest:
        common = {
            "track_high_thresh",
            "track_low_thresh",
            "new_track_thresh",
            "track_buffer",
            "match_thresh",
            "fuse_score",
        }
        botsort = {
            "gmc_method",
            "proximity_thresh",
            "appearance_thresh",
            "with_reid",
        }
        allowed = common | (botsort if self.tracker == "botsort" else set())
        unknown = sorted(set(self.tracker_options) - allowed)
        if unknown:
            raise ValueError(f"Unsupported {self.tracker} options: {', '.join(unknown)}")
        thresholds = {
            "track_high_thresh",
            "track_low_thresh",
            "new_track_thresh",
            "match_thresh",
            "proximity_thresh",
            "appearance_thresh",
        }
        for name in thresholds & self.tracker_options.keys():
            value = self.tracker_options[name]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be numeric")
            if not 0 <= float(value) <= 1:
                raise ValueError(f"{name} must be between zero and one")
        if "track_buffer" in self.tracker_options:
            value = self.tracker_options["track_buffer"]
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 10000:
                raise ValueError("track_buffer must be an integer between 1 and 10000")
        for name in {"fuse_score", "with_reid"} & self.tracker_options.keys():
            if not isinstance(self.tracker_options[name], bool):
                raise ValueError(f"{name} must be boolean")
        if self.tracker_options.get("with_reid") is True:
            raise ValueError(
                "BoT-SORT ReID is disabled until a local ReID checkpoint can be selected"
            )
        if "gmc_method" in self.tracker_options and self.tracker_options["gmc_method"] not in {
            "sparseOptFlow",
            "orb",
            "none",
        }:
            raise ValueError("gmc_method must be sparseOptFlow, orb, or none")
        low = float(self.tracker_options.get("track_low_thresh", 0.1))
        high = float(self.tracker_options.get("track_high_thresh", 0.25))
        if low > high:
            raise ValueError("track_low_thresh cannot exceed track_high_thresh")
        return self


class VideoZone(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    x_min: float = Field(ge=0)
    y_min: float = Field(ge=0)
    x_max: float = Field(gt=0)
    y_max: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_bounds(self) -> VideoZone:
        if self.x_max <= self.x_min or self.y_max <= self.y_min:
            raise ValueError("Video zones must have positive width and height")
        return self


class VideoZoneCreateRequest(VideoZone):
    pass


class VideoZoneUpdateRequest(VideoZone):
    expected_revision: int = Field(ge=1)


class VideoZoneResponse(VideoZone):
    id: str
    video_id: str
    revision: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime


class VideoAnalyticsRequest(BaseModel):
    zones: list[VideoZone] = Field(default_factory=list)
    include_saved_zones: bool = True
    heatmap_bins_x: int = Field(default=20, ge=2, le=100)
    heatmap_bins_y: int = Field(default=20, ge=2, le=100)
    activity_speed_threshold_pixels_per_second: float = Field(default=1.0, ge=0)
    sampling: Literal["interpolated", "observations"] = "interpolated"
    persist_result: bool = True


class VideoTrajectorySample(BaseModel):
    observation_id: str | None
    frame_index: int = Field(ge=0)
    timestamp_seconds: float = Field(ge=0)
    center_x_pixels: float
    center_y_pixels: float
    center_x_physical: float | None
    center_y_physical: float | None
    distance_from_previous_pixels: float | None = Field(default=None, ge=0)
    distance_from_previous_physical: float | None = Field(default=None, ge=0)
    speed_pixels_per_second: float | None = Field(default=None, ge=0)
    speed_physical_per_second: float | None = Field(default=None, ge=0)
    acceleration_pixels_per_second_squared: float | None = Field(default=None, ge=0)
    turning_angle_degrees: float | None = Field(default=None, ge=0, le=180)
    angular_velocity_degrees_per_second: float | None = Field(default=None, ge=0)
    interpolated: bool
    manual_edit: bool


class VideoZoneEvent(BaseModel):
    track_id: str
    zone_name: str
    event_type: Literal["entry", "exit"]
    frame_index: int = Field(ge=0)
    timestamp_seconds: float = Field(ge=0)


class VideoTrackAnalytics(BaseModel):
    track_id: str
    tracker_id: int
    label_class_id: str | None
    first_frame: int
    last_frame: int
    observed_frame_count: int
    persisted_observation_count: int = 0
    duration_seconds: float
    distance_pixels: float
    total_path_length_pixels: float = 0.0
    net_displacement_pixels: float = 0.0
    path_tortuosity: float | None = None
    mean_speed_pixels_per_second: float
    maximum_speed_pixels_per_second: float
    mean_acceleration_pixels_per_second_squared: float = 0.0
    maximum_acceleration_pixels_per_second_squared: float = 0.0
    mean_turning_angle_degrees: float | None = None
    cumulative_turning_angle_degrees: float = 0.0
    mean_angular_velocity_degrees_per_second: float | None = None
    mean_distance_to_wall_pixels: float = 0.0
    active_time_seconds: float
    inactive_time_seconds: float
    distance_physical: float | None
    net_displacement_physical: float | None = None
    mean_speed_physical_per_second: float | None
    maximum_speed_physical_per_second: float | None
    mean_acceleration_physical_per_second_squared: float | None = None
    maximum_acceleration_physical_per_second_squared: float | None = None
    mean_distance_to_wall_physical: float | None = None
    physical_unit: str | None
    zone_time_seconds: dict[str, float]
    trajectory: list[VideoTrajectorySample] = Field(default_factory=list)


class VideoFrameSchoolAnalytics(BaseModel):
    frame_index: int
    timestamp_seconds: float
    active_track_count: int
    school_centroid_x_pixels: float | None = None
    school_centroid_y_pixels: float | None = None
    mean_nearest_neighbor_pixels: float | None
    mean_pairwise_distance_pixels: float | None = None
    school_spread_pixels: float | None
    polarization: float | None = Field(default=None, ge=0, le=1)
    mean_nearest_neighbor_physical: float | None
    mean_pairwise_distance_physical: float | None = None
    school_spread_physical: float | None
    school_centroid_x_physical: float | None = None
    school_centroid_y_physical: float | None = None


class VideoHeatmapCell(BaseModel):
    column: int
    row: int
    observation_count: int
    occupancy_seconds: float


class VideoAnalyticsResponse(BaseModel):
    analysis_id: str | None = None
    video_id: str
    fps: float
    coordinate_unit: Literal["pixels"] = "pixels"
    timing_source: Literal["video_fps", "observation_timestamps"] = "video_fps"
    distance_per_pixel: float | None
    physical_unit: str | None
    tracks: list[VideoTrackAnalytics]
    school_by_frame: list[VideoFrameSchoolAnalytics]
    heatmap_bins_x: int
    heatmap_bins_y: int
    heatmap: list[VideoHeatmapCell]
    zone_events: list[VideoZoneEvent] = Field(default_factory=list)
    configuration: dict[str, Any] = Field(default_factory=dict)
    source_track_revisions: list[dict[str, Any]] = Field(default_factory=list)
    analysis_sha256: str | None = None
    warnings: list[str]
