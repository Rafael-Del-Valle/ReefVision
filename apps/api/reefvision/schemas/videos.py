"""Video import, tracking, analytics, and export schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class VideoImportResponse(BaseModel):
    video: VideoAssetResponse
    duplicate: bool = False


class VideoCalibrationUpdate(BaseModel):
    distance_per_pixel: float = Field(gt=0)
    unit: str = Field(default="cm", min_length=1, max_length=32)
    source: str = Field(default="manual", min_length=1, max_length=100)
    notes: str | None = Field(default=None, max_length=1000)


class VideoTrackKeyframe(BaseModel):
    frame_index: int = Field(ge=0)
    x_min: float = Field(ge=0)
    y_min: float = Field(ge=0)
    x_max: float = Field(gt=0)
    y_max: float = Field(gt=0)
    confidence: float | None = Field(default=None, ge=0, le=1)
    source: str = Field(default="human", min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_box(self) -> VideoTrackKeyframe:
        if self.x_max <= self.x_min or self.y_max <= self.y_min:
            raise ValueError("Video track boxes must have positive width and height")
        return self


class VideoExtractJobRequest(BaseModel):
    video_path: str = Field(min_length=1)
    frames_path: str = Field(min_length=1)
    every_n_frames: int = Field(default=1, ge=1)


class VideoTrackCreateRequest(BaseModel):
    video_id: str = Field(min_length=1, max_length=36)
    label_class_id: str | None = Field(default=None, max_length=36)
    track_number: int = Field(ge=1)
    geometry_kind: str = Field(default="bounding_box", min_length=1, max_length=30)
    keyframes: list[VideoTrackKeyframe] = Field(min_length=1)
    interpolation: VideoTrackInterpolation = "linear"
    status: str = Field(default="verified", min_length=1, max_length=30)

    @model_validator(mode="after")
    def unique_frames(self) -> VideoTrackCreateRequest:
        frames = [item.frame_index for item in self.keyframes]
        if len(set(frames)) != len(frames):
            raise ValueError("Track keyframes must use unique frame indices")
        return self


class VideoTrackUpdateRequest(BaseModel):
    label_class_id: str | None = Field(default=None, max_length=36)
    keyframes: list[VideoTrackKeyframe] | None = None
    interpolation: VideoTrackInterpolation | None = None
    status: str | None = Field(default=None, max_length=30)


class VideoTrackResponse(BaseModel):
    id: str
    video_id: str
    label_class_id: str | None
    track_number: int
    geometry_kind: str
    keyframes: list[VideoTrackKeyframe]
    interpolation: str
    status: str
    metadata_json: dict[str, Any]


class VideoTrackingJobRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=36)
    tracker: VideoTrackerKind = "bytetrack"
    device: str = Field(default="auto", min_length=1, max_length=60)
    confidence_threshold: float = Field(default=0.25, ge=0, le=1)
    iou_threshold: float = Field(default=0.45, ge=0, le=1)
    every_n_frames: int = Field(default=1, ge=1, le=1000)
    replace_generated_tracks: bool = True


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


class VideoAnalyticsRequest(BaseModel):
    zones: list[VideoZone] = Field(default_factory=list)
    heatmap_bins_x: int = Field(default=20, ge=2, le=100)
    heatmap_bins_y: int = Field(default=20, ge=2, le=100)
    activity_speed_threshold_pixels_per_second: float = Field(default=1.0, ge=0)


class VideoTrackAnalytics(BaseModel):
    track_id: str
    tracker_id: int
    label_class_id: str | None
    first_frame: int
    last_frame: int
    observed_frame_count: int
    duration_seconds: float
    distance_pixels: float
    mean_speed_pixels_per_second: float
    maximum_speed_pixels_per_second: float
    active_time_seconds: float
    inactive_time_seconds: float
    distance_physical: float | None
    mean_speed_physical_per_second: float | None
    maximum_speed_physical_per_second: float | None
    physical_unit: str | None
    zone_time_seconds: dict[str, float]


class VideoFrameSchoolAnalytics(BaseModel):
    frame_index: int
    timestamp_seconds: float
    active_track_count: int
    mean_nearest_neighbor_pixels: float | None
    school_spread_pixels: float | None
    mean_nearest_neighbor_physical: float | None
    school_spread_physical: float | None


class VideoHeatmapCell(BaseModel):
    column: int
    row: int
    observation_count: int
    occupancy_seconds: float


class VideoAnalyticsResponse(BaseModel):
    video_id: str
    fps: float
    distance_per_pixel: float | None
    physical_unit: str | None
    tracks: list[VideoTrackAnalytics]
    school_by_frame: list[VideoFrameSchoolAnalytics]
    heatmap_bins_x: int
    heatmap_bins_y: int
    heatmap: list[VideoHeatmapCell]
    warnings: list[str]
