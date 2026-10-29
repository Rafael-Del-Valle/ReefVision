from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _MovementAnalyticsModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
    )


class GeographicMovementObservation(_MovementAnalyticsModel):
    """Minimal persisted-observation projection required for movement analytics."""

    observation_id: str = Field(min_length=1)
    track_id: str | None
    video_asset_id: str = Field(min_length=1)
    frame_index: int = Field(ge=0)
    frame_time_s: float
    latitude_deg: float = Field(ge=-90.0, le=90.0)
    longitude_deg: float = Field(ge=-180.0, le=180.0)
    crs: str = Field(min_length=1)


class GeographicCoordinate(_MovementAnalyticsModel):
    latitude_deg: float = Field(ge=-90.0, le=90.0)
    longitude_deg: float = Field(ge=-180.0, le=180.0)
    crs: str = Field(min_length=1)


class GeographicMovementSegment(_MovementAnalyticsModel):
    track_id: str
    video_asset_id: str

    start_observation_id: str
    end_observation_id: str

    start_frame_index: int = Field(ge=0)
    end_frame_index: int = Field(ge=0)

    start_frame_time_s: float
    end_frame_time_s: float
    elapsed_time_s: float

    start_location: GeographicCoordinate
    end_location: GeographicCoordinate

    distance_m: float = Field(ge=0.0)
    speed_m_s: float | None = Field(default=None, ge=0.0)
    initial_bearing_deg: float | None = Field(
        default=None,
        ge=0.0,
        lt=360.0,
        description=(
            "Initial azimuth of the WGS84 geodesic from the start location to the end "
            "location, in degrees clockwise from true north. Null for coincident locations. "
            "This describes sampled geographic displacement, not organism body orientation."
        ),
    )
    cumulative_distance_m: float = Field(ge=0.0)

    speed_valid: bool
    invalid_reason: Literal["non_positive_elapsed_time"] | None = None


class GeographicTrackAnalytics(_MovementAnalyticsModel):
    track_id: str
    video_asset_id: str

    observation_count: int = Field(ge=0)
    segment_count: int = Field(ge=0)

    first_frame_index: int | None = Field(default=None, ge=0)
    last_frame_index: int | None = Field(default=None, ge=0)

    first_frame_time_s: float | None = None
    last_frame_time_s: float | None = None
    elapsed_time_s: float | None = None

    total_distance_m: float = Field(ge=0.0)
    net_displacement_m: float = Field(ge=0.0)

    mean_speed_m_s: float | None = Field(default=None, ge=0.0)
    max_segment_speed_m_s: float | None = Field(default=None, ge=0.0)

    start_location: GeographicCoordinate | None = None
    end_location: GeographicCoordinate | None = None

    segments: list[GeographicMovementSegment] = Field(
        default_factory=list,
    )
