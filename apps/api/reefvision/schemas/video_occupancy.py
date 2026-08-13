"""Grid-based fish occupancy analytics schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class VideoOccupancyRequest(BaseModel):
    track_ids: list[str] = Field(min_length=1, max_length=1000)
    grid_rows: int = Field(default=3, ge=1, le=50)
    grid_columns: int = Field(default=3, ge=1, le=50)
    start_frame: int | None = Field(default=None, ge=0)
    end_frame: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_selection(self) -> VideoOccupancyRequest:
        if len(set(self.track_ids)) != len(self.track_ids):
            raise ValueError("Occupancy track IDs must be unique")
        if (
            self.start_frame is not None
            and self.end_frame is not None
            and self.end_frame < self.start_frame
        ):
            raise ValueError("end_frame must be greater than or equal to start_frame")
        return self


class VideoOccupancyCell(BaseModel):
    row: int = Field(ge=0)
    column: int = Field(ge=0)
    x_min_pixels: float
    y_min_pixels: float
    x_max_pixels: float
    y_max_pixels: float
    observation_count: int = Field(ge=0)
    observation_fraction: float = Field(ge=0, le=1)
    occupied_frame_count: int = Field(ge=0)
    occupied_frame_fraction: float = Field(ge=0, le=1)
    unique_track_count: int = Field(ge=0)
    dwell_seconds: float = Field(ge=0)


class VideoTrackOccupancySummary(BaseModel):
    track_id: str
    track_number: int
    label_class_id: str
    observation_count: int = Field(ge=0)
    dwell_seconds: float = Field(ge=0)
    occupied_cell_count: int = Field(ge=0)
    most_occupied_row: int | None
    most_occupied_column: int | None
    most_occupied_fraction: float | None = Field(default=None, ge=0, le=1)


class VideoOccupancyResponse(BaseModel):
    schema_version: Literal["video-occupancy-0001"]
    video_id: str
    track_ids: list[str]
    start_frame: int
    end_frame: int
    grid_rows: int
    grid_columns: int
    video_width_pixels: int
    video_height_pixels: int
    trajectory_policy: Literal["configured_track_interpolation"]
    frames_with_tracks: int = Field(ge=0)
    track_frame_observations: int = Field(ge=0)
    total_track_seconds: float = Field(ge=0)
    cells: list[VideoOccupancyCell]
    per_track: list[VideoTrackOccupancySummary]
