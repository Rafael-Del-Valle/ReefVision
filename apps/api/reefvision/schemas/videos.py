"""Managed video, sparse track, interpolation, analytics, and export schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

TrackInterpolation = Literal["linear", "hold"]
TrackGeometryKind = Literal["bbox"]
VideoTrackerConfig = Literal["bytetrack.yaml", "botsort.yaml"]


class VideoExtractRequest(BaseModel):
    every_n_frames: int = Field(default=1, ge=1, le=10000)


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

    model_config = {"from_attributes": True}


class VideoCalibrationUpdate(BaseModel):
    distance_per_pixel: float = Field(gt=0)
    unit: str = Field(default="cm", min_length=1, max_length=32)
    source: str = Field(default="manual", min_length=1, max_length=100)
    notes: str | None = Field(default=None, max_length=1000)


class VideoTrackKeyframe(BaseModel):
    frame: int = Field(ge=0)
    bbox: tuple[float, float, float, float]
    confidence: float | None = Field(default=None, ge=0, le=1)

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


class VideoZone(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    x_min: float = Field(ge=0)
    y_min: float = Field(ge=0)
    x_max: float = Field(gt=0)
    y_max: float = Field(gt=0)

    @model_validator(mode="after")
    def positive_zone(self) -> VideoZone:
        if self.x_max <= self.x_min or self.y_max <= self.y_min:
            raise ValueError("Video zones require positive width and height")
        return self


class VideoBehaviorAnalyticsRequest(BaseModel):
    zones: list[VideoZone] = Field(default_factory=list)
    heatmap_bins_x: int = Field(default=20, ge=2, le=100)
    heatmap_bins_y: int = Field(default=20, ge=2, le=100)
    activity_speed_threshold_pixels_per_second: float = Field(default=1.0, ge=0)


class VideoBehaviorTrackAnalytics(BaseModel):
    track_id: str
    track_number: int
    label_class_id: str
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
    frame: int
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


class VideoBehaviorAnalyticsResponse(BaseModel):
    video_id: str
    fps: float
    distance_per_pixel: float | None
    physical_unit: str | None
    tracks: list[VideoBehaviorTrackAnalytics]
    school_by_frame: list[VideoFrameSchoolAnalytics]
    heatmap_bins_x: int
    heatmap_bins_y: int
    heatmap: list[VideoHeatmapCell]
    warnings: list[str]


class VideoTrackingCreateRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=36)
    tracker: VideoTrackerConfig = "bytetrack.yaml"
    confidence: float = Field(default=0.25, ge=0, le=1)
    iou: float = Field(default=0.5, ge=0, le=1)
    device: str = Field(default="auto", min_length=1, max_length=60)
    minimum_track_frames: int = Field(default=2, ge=1, le=1000000)
