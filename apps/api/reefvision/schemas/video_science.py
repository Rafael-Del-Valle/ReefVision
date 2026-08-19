"""Spatial calibration and group-level video science schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, FiniteFloat, model_validator

DistanceUnit = Literal["mm", "cm", "m"]


class VideoSpatialCalibrationSetRequest(BaseModel):
    unit: DistanceUnit
    reference_distance: float = Field(gt=0)
    reference_pixels: float = Field(gt=0)
    method: str = Field(default="known_length", min_length=1, max_length=80)
    reference_label: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)


class VideoSpatialCalibrationResponse(BaseModel):
    schema_version: Literal["video-spatial-calibration-0001"]
    video_id: str
    unit: DistanceUnit
    reference_distance: float
    reference_pixels: float
    pixels_per_unit: float
    units_per_pixel: float
    method: str
    reference_label: str | None
    notes: str | None
    video_revision: int


class CalibratedVideoTrackAnalyticsResponse(BaseModel):
    schema_version: Literal["calibrated-video-track-analytics-0001"]
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
    distance_unit: DistanceUnit
    path_length: float
    mean_speed_per_second: float
    maximum_speed_per_second: float
    displacement: float
    calibration: VideoSpatialCalibrationResponse


class VideoSchoolingAnalyticsRequest(BaseModel):
    track_ids: list[str] = Field(min_length=2, max_length=1000)
    start_frame: int | None = Field(default=None, ge=0)
    end_frame: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_selection(self) -> VideoSchoolingAnalyticsRequest:
        if len(set(self.track_ids)) != len(self.track_ids):
            raise ValueError("Schooling track IDs must be unique")
        if (
            self.start_frame is not None
            and self.end_frame is not None
            and self.end_frame < self.start_frame
        ):
            raise ValueError("end_frame must be greater than or equal to start_frame")
        return self


class VideoSchoolingFrameMetrics(BaseModel):
    frame: int
    timestamp_seconds: float
    active_track_count: int
    mean_pairwise_distance_pixels: float
    mean_nearest_neighbor_distance_pixels: float
    mean_distance_to_centroid_pixels: float
    mean_pairwise_distance: float
    mean_nearest_neighbor_distance: float
    mean_distance_to_centroid: float
    mean_speed_pixels_per_second: float | None
    mean_speed_per_second: float | None
    polarization: float | None = Field(default=None, ge=0, le=1)


class VideoSchoolingAnalyticsResponse(BaseModel):
    schema_version: Literal["video-schooling-analytics-0001"]
    video_id: str
    track_ids: list[str]
    start_frame: int
    end_frame: int
    trajectory_policy: Literal["configured_track_interpolation"]
    frames_evaluated: int
    mean_group_size: float
    mean_pairwise_distance_pixels: float
    mean_nearest_neighbor_distance_pixels: float
    mean_distance_to_centroid_pixels: float
    mean_pairwise_distance: float
    mean_nearest_neighbor_distance: float
    mean_distance_to_centroid: float
    mean_speed_pixels_per_second: float | None
    mean_speed_per_second: float | None
    mean_polarization: float | None
    distance_unit: DistanceUnit
    calibration: VideoSpatialCalibrationResponse
    frames: list[VideoSchoolingFrameMetrics]


class VideoCameraIntrinsicsSetRequest(BaseModel):
    fx_px: FiniteFloat = Field(gt=0)
    fy_px: FiniteFloat = Field(gt=0)
    cx_px: FiniteFloat
    cy_px: FiniteFloat
    method: str = Field(default="camera_calibration", min_length=1, max_length=80)
    notes: str | None = Field(default=None, max_length=2000)


class VideoCameraIntrinsicsResponse(BaseModel):
    schema_version: Literal["video-camera-intrinsics-0001"]
    video_id: str
    fx_px: float
    fy_px: float
    cx_px: float
    cy_px: float
    method: str
    notes: str | None
    video_revision: int


class VideoDepthSample(BaseModel):
    track_id: str = Field(min_length=1, max_length=100)
    frame: int = Field(ge=0)
    depth: FiniteFloat = Field(gt=0)
    confidence: float | None = Field(default=None, ge=0, le=1)


class VideoDepthTrackAnalyticsRequest(BaseModel):
    unit: DistanceUnit = "m"
    samples: list[VideoDepthSample] = Field(min_length=2, max_length=2_000_000)
    maximum_frame_gap: int | None = Field(default=None, ge=1, le=100_000)

    @model_validator(mode="after")
    def validate_samples(self) -> VideoDepthTrackAnalyticsRequest:
        identities = [(sample.track_id, sample.frame) for sample in self.samples]
        if len(identities) != len(set(identities)):
            raise ValueError("Depth samples must use unique track/frame pairs")
        return self


class VideoDepthTrackPoint3D(BaseModel):
    frame: int
    timestamp_seconds: float
    center_x_px: float
    center_y_px: float
    x: float
    y: float
    z: float
    depth_confidence: float | None


class VideoDepthTrack3DAnalytics(BaseModel):
    track_id: str
    track_number: int
    label_class_id: str
    observed_frame_count: int
    first_frame: int
    last_frame: int
    duration_seconds: float
    path_length_3d: float
    displacement_3d: float
    mean_speed_3d_per_second: float
    maximum_speed_3d_per_second: float
    mean_depth: float
    minimum_depth: float
    maximum_depth: float
    skipped_gap_count: int
    points: list[VideoDepthTrackPoint3D]


class VideoDepthTrackAnalyticsResponse(BaseModel):
    schema_version: Literal["video-depth-track-analytics-0001"]
    video_id: str
    unit: DistanceUnit
    camera_intrinsics: VideoCameraIntrinsicsResponse
    tracks: list[VideoDepthTrack3DAnalytics]
    warnings: list[str]
