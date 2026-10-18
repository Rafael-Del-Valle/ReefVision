"""1.2 contracts for exploratory repeated-organism measurements."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class MonitoringObservation(BaseModel):
    """A caller-supplied observation, not an authenticated scientific record."""

    organism_id: str = Field(min_length=1, max_length=150)
    metric_name: str = Field(min_length=1, max_length=100)
    source_record_id: str = Field(min_length=1, max_length=150)
    observed_at: datetime
    value: float = Field(ge=0)
    unit: str = Field(min_length=1, max_length=32)

    @field_validator("organism_id", "metric_name", "source_record_id", "unit")
    @classmethod
    def nonempty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Observation identifiers and units cannot be blank")
        return stripped

    @field_validator("observed_at")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Observation time must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("value")
    @classmethod
    def finite_value(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("Observation values must be finite")
        return value


class LongitudinalAnalysisRequest(BaseModel):
    observations: list[MonitoringObservation] = Field(min_length=2, max_length=10000)


class LongitudinalChange(BaseModel):
    organism_id: str
    metric_name: str
    unit: str
    first_observed_at: datetime
    last_observed_at: datetime
    baseline_source_record_id: str
    final_source_record_id: str
    initial_value: float
    final_value: float
    absolute_change: float
    percent_change: float | None
    elapsed_days: float
    change_per_day: float
    observation_count: int


class LongitudinalAnalysisResponse(BaseModel):
    analysis_level: Literal["organism"] = "organism"
    evidence_level: Literal["caller_supplied_unverified"] = "caller_supplied_unverified"
    observation_count: int
    evaluated_series_count: int
    incomplete_series_count: int
    changes: list[LongitudinalChange]
    limitations: list[str] = Field(default_factory=list)
