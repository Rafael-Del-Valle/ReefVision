"""Normalized telemetry values and video-level persistence metadata."""

from typing import Literal

from pydantic import BaseModel, Field, FiniteFloat


class TelemetrySample(BaseModel):
    """Relative cue time, GPS degrees, SI distances/speeds, and source attitude.

    Attitude signs/axes and absolute-altitude datum are source conventions, not
    calibrated world coordinates. Explicit frame counters retain source numbering.
    A focal length may be 35mm equivalent; it is not a calibrated camera intrinsic.
    """

    model_config = {"frozen": True}

    sample_index: int = Field(ge=0)
    time_s: FiniteFloat = Field(ge=0)
    frame_number: int | None = Field(default=None, ge=0)
    latitude: FiniteFloat | None = Field(default=None, ge=-90, le=90)
    longitude: FiniteFloat | None = Field(default=None, ge=-180, le=180)
    relative_altitude_m: FiniteFloat | None = None
    absolute_altitude_m: FiniteFloat | None = None
    gimbal_yaw_deg: FiniteFloat | None = None
    gimbal_pitch_deg: FiniteFloat | None = None
    gimbal_roll_deg: FiniteFloat | None = None
    aircraft_yaw_deg: FiniteFloat | None = None
    aircraft_pitch_deg: FiniteFloat | None = None
    aircraft_roll_deg: FiniteFloat | None = None
    horizontal_speed_mps: FiniteFloat | None = Field(default=None, ge=0)
    vertical_speed_mps: FiniteFloat | None = None
    iso: int | None = Field(default=None, gt=0)
    shutter_speed_s: FiniteFloat | None = Field(default=None, gt=0)
    focal_length_mm: FiniteFloat | None = Field(default=None, gt=0)
    focal_length_raw: str | None = None
    digital_zoom_ratio: FiniteFloat | None = Field(default=None, gt=0)


class TelemetryMetadata(BaseModel):
    found: bool = False
    available: bool = False
    source_type: Literal["dji_srt"] | None = None
    source_path: str | None = None
    path_kind: Literal["managed", "external"] | None = None
    sample_count: int = Field(default=0, ge=0)
    error: str | None = None


class TelemetryMatch(BaseModel):
    """Signed delta = sample time - request time; error is its absolute value."""

    model_config = {"frozen": True}

    sample: TelemetrySample
    requested_time_s: float
    delta_s: float

    @property
    def error_s(self) -> float:
        return abs(self.delta_s)
