"""1.2 contracts for exploratory repeated-organism measurements."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from reefvision.domain.experimental_unit_policy import require_ecological_unit_type
from reefvision.schemas.scientific_provenance import ScientificInputProvenance


class MonitoringObservation(BaseModel):
    """A caller-supplied observation, not an authenticated scientific record."""

    organism_id: str = Field(min_length=1, max_length=150)
    metric_name: str = Field(min_length=1, max_length=100)
    source_record_id: str = Field(min_length=1, max_length=150)
    observed_at: datetime
    value: float = Field(ge=0)
    unit: str = Field(min_length=1, max_length=32)
    experimental_unit_id: str | None = Field(default=None, max_length=150)
    experimental_unit_type: str | None = Field(default=None, max_length=100)

    @field_validator(
        "organism_id",
        "metric_name",
        "source_record_id",
        "unit",
        "experimental_unit_id",
        "experimental_unit_type",
    )
    @classmethod
    def nonempty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("Observation identifiers and units cannot be blank")
        return stripped

    @field_validator("experimental_unit_type")
    @classmethod
    def reject_technical_units(cls, value: str | None) -> str | None:
        return require_ecological_unit_type(value)

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
    experimental_unit_type: str | None = Field(default=None, max_length=100)

    @field_validator("experimental_unit_type")
    @classmethod
    def nonempty_unit_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("Experimental unit type cannot be blank")
        return require_ecological_unit_type(stripped)

    @model_validator(mode="after")
    def resolve_observation_unit_type(self) -> LongitudinalAnalysisRequest:
        declared = {
            item.experimental_unit_type
            for item in self.observations
            if item.experimental_unit_type is not None
        }
        if len(declared) > 1:
            raise ValueError("Observations declare conflicting experimental unit types")
        if declared:
            only = next(iter(declared))
            if self.experimental_unit_type is not None and self.experimental_unit_type != only:
                raise ValueError("Request and observations disagree on experimental unit type")
            self.experimental_unit_type = only
        return self


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


class ExperimentalUnitSummary(BaseModel):
    """Descriptive unit-level mean; never an organism-level replication count."""

    experimental_unit_id: str
    metric_name: str
    unit: str
    organism_count: int
    baseline_at: datetime
    final_at: datetime
    mean_absolute_change: float
    mean_change_per_day: float


class PopulationUnitSummary(BaseModel):
    """One vote per eligible declared experimental unit and UTC date window."""

    metric_name: str
    unit: str
    baseline_date: date
    final_date: date
    independent_unit_count: int
    contributing_organism_count: int
    experimental_unit_ids: list[str]
    mean_unit_absolute_change: float
    mean_unit_change_per_day: float


class ExperimentalUnitCoverage(BaseModel):
    """Per-unit, per-metric follow-up denominators; not verified replication."""

    experimental_unit_id: str
    metric_name: str
    observed_organism_count: int = Field(ge=1)
    complete_organism_count: int = Field(ge=0)
    missing_followup_organism_count: int = Field(ge=0)
    missing_organism_ids: list[str] = Field(default_factory=list)
    eligible_for_summary: bool
    exclusion_reason: Literal["missing_followup", "nonmatching_sampling_window"] | None = None


class ExcludedExperimentalUnit(BaseModel):
    experimental_unit_id: str
    metric_name: str
    reason: Literal["missing_followup", "nonmatching_sampling_window"]


class LongitudinalAnalysisResponse(BaseModel):
    analysis_level: Literal["organism"] = "organism"
    evidence_level: Literal["caller_supplied_unverified"] = "caller_supplied_unverified"
    observation_count: int
    analysis_provenance: ScientificInputProvenance
    evaluated_series_count: int
    incomplete_series_count: int
    changes: list[LongitudinalChange]
    experimental_unit_type: str | None = None
    independent_unit_count: int | None = None
    unit_summaries: list[ExperimentalUnitSummary] = Field(default_factory=list)
    population_summaries: list[PopulationUnitSummary] = Field(default_factory=list)
    excluded_units: list[ExcludedExperimentalUnit] = Field(default_factory=list)
    unit_coverage: list[ExperimentalUnitCoverage] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
