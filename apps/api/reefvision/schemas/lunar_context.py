"""Explicit UTC input and qualified offline lunar phase/illumination outputs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from reefvision.schemas.scientific_data import ScientificModel, utc_timestamp

LunarPhase = Literal[
    "new_moon",
    "waxing_crescent",
    "first_quarter",
    "waxing_gibbous",
    "full_moon",
    "waning_gibbous",
    "last_quarter",
    "waning_crescent",
]


class LunarContextRequest(ScientificModel):
    observed_at: datetime

    _utc = field_validator("observed_at")(utc_timestamp)

    @model_validator(mode="after")
    def require_supported_epoch(self) -> LunarContextRequest:
        if not 1900 <= self.observed_at.year <= 2100:
            raise ValueError("Low-precision lunar calculation supports 1900–2100 UTC")
        return self


class LunarContextResponse(ScientificModel):
    schema_version: Literal["1.1.0"] = "1.1.0"
    algorithm: Literal["reefvision-low-precision-ecliptic-longitude-1"]
    project_id: UUID
    observed_at: datetime
    phase: LunarPhase
    phase_fraction: float = Field(ge=0, lt=1)
    illuminated_fraction: float = Field(ge=0, le=1)
    approximate_lunar_age_days: float = Field(ge=0, lt=30)
    reference_frame: Literal["geocentric_approximate"]
    computation: Literal["offline_deterministic"]
    content_sha256: str = Field(min_length=64, max_length=64)
    methodological_notes: list[str]
