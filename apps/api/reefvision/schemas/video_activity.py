"""Calibrated fish activity and movement-bout schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from reefvision.schemas.video_science import DistanceUnit, VideoSpatialCalibrationResponse


class VideoTrackActivityRequest(BaseModel):
    speed_threshold_per_second: float = Field(ge=0)
    start_frame: int | None = Field(default=None, ge=0)
    end_frame: int | None = Field(default=None, ge=0)
    minimum_active_bout_seconds: float = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def validate_range(self) -> VideoTrackActivityRequest:
        if (
            self.start_frame is not None
            and self.end_frame is not None
            and self.end_frame < self.start_frame
        ):
            raise ValueError("end_frame must be greater than or equal to start_frame")
        return self


class VideoActivityInterval(BaseModel):
    start_frame: int
    end_frame: int
    start_time_seconds: float
    end_time_seconds: float
    duration_seconds: float
    distance_pixels: float
    distance: float
    speed_pixels_per_second: float
    speed_per_second: float
    active: bool


class VideoActivityBout(BaseModel):
    state: Literal["active", "rest"]
    start_frame: int
    end_frame: int
    start_time_seconds: float
    end_time_seconds: float
    duration_seconds: float
    interval_count: int


class VideoTrackActivityResponse(BaseModel):
    schema_version: Literal["video-track-activity-0001"]
    track_id: str
    video_id: str
    track_number: int
    label_class_id: str
    trajectory_policy: Literal["configured_track_interpolation"]
    start_frame: int
    end_frame: int
    distance_unit: DistanceUnit
    speed_threshold_per_second: float
    speed_threshold_pixels_per_second: float
    minimum_active_bout_seconds: float
    evaluated_seconds: float
    active_seconds: float
    rest_seconds: float
    active_fraction: float = Field(ge=0, le=1)
    active_bout_count: int
    rest_bout_count: int
    mean_active_bout_seconds: float | None
    maximum_active_bout_seconds: float | None
    mean_rest_bout_seconds: float | None
    mean_active_speed_per_second: float | None
    maximum_speed_per_second: float | None
    calibration: VideoSpatialCalibrationResponse
    intervals: list[VideoActivityInterval]
    bouts: list[VideoActivityBout]
