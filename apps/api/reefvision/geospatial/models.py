"""Normalized telemetry values and video-level persistence metadata."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, FiniteFloat, field_validator, model_validator


class TelemetrySample(BaseModel):
    """Relative cue time, GPS degrees, SI distances/speeds, and source attitude.

    Attitude signs/axes and absolute-altitude datum are source conventions, not
    calibrated world coordinates. Explicit frame counters retain source numbering.
    A focal length may be 35mm equivalent; it is not a calibrated camera intrinsic.
    """

    model_config = {"frozen": True}

    sample_index: int = Field(ge=0)
    time_s: FiniteFloat = Field(ge=0)
    wall_clock: datetime | None = None
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

    @field_validator("wall_clock")
    @classmethod
    def wall_clock_has_no_inferred_zone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is not None and value.utcoffset() is not None:
            raise ValueError("DJI SRT wall-clock timestamps must be timezone-naive")
        return value


TelemetryFieldSource = Literal["airdata", "dji_srt"]


class TelemetryMetadata(BaseModel):
    found: bool = False
    available: bool = False
    source_type: Literal["dji_srt", "airdata"] | None = None
    source_path: str | None = None
    path_kind: Literal["managed", "external"] | None = None
    sample_count: int = Field(default=0, ge=0)
    wall_clock_sample_count: int = Field(default=0, ge=0)
    utc_offset_minutes: int | None = Field(default=None, ge=-840, le=840)
    utc_offset_evidence: str | None = None
    content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    error: str | None = None

    @model_validator(mode="after")
    def valid_absolute_time_evidence(self) -> TelemetryMetadata:
        evidence = (self.utc_offset_evidence or "").strip() or None
        if (self.utc_offset_minutes is None) != (evidence is None):
            raise ValueError("Telemetry UTC offset and evidence must be supplied together")
        if self.utc_offset_minutes is not None and self.wall_clock_sample_count == 0:
            raise ValueError("Telemetry UTC alignment requires SRT wall-clock samples")
        self.utc_offset_evidence = evidence
        return self


class TelemetryProvenance(BaseModel):
    """Source identity for fields merged across aligned telemetry streams."""

    model_config = {"frozen": True}

    position_source: TelemetryFieldSource | None = None
    relative_altitude_source: TelemetryFieldSource | None = None
    gimbal_yaw_source: TelemetryFieldSource | None = None
    gimbal_pitch_source: TelemetryFieldSource | None = None
    gimbal_roll_source: TelemetryFieldSource | None = None
    airdata_delta_s: float | None = None
    srt_delta_s: float | None = None
    airdata_time_offset_s: float = 0.0
    airdata_time_offset_evidence: str | None = None


class TelemetryMatch(BaseModel):
    """Signed delta = effective source sample time - request time."""

    model_config = {"frozen": True}

    sample: TelemetrySample
    requested_time_s: float
    delta_s: float
    provenance: TelemetryProvenance | None = None

    @property
    def error_s(self) -> float:
        return abs(self.delta_s)
