"""1.2 contracts for exploratory repeated-organism measurements."""

from __future__ import annotations

import math
import re
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from reefvision.domain.ecology_lineage_policy import (
    canonical_declared_unit_type,
    ecological_unit_types_equivalent,
)
from reefvision.domain.experimental_unit_policy import require_ecological_unit_type
from reefvision.schemas.scientific_provenance import ScientificInputProvenance


class MonitoringObservation(BaseModel):
    """A caller-supplied observation, not an authenticated scientific record."""

    model_config = ConfigDict(extra="forbid")

    organism_id: str = Field(min_length=1, max_length=150)
    parent_colony_id: str | None = Field(default=None, max_length=150)
    metric_name: str = Field(min_length=1, max_length=100)
    source_record_id: str = Field(min_length=1, max_length=150)
    observed_at: datetime
    value: float = Field(ge=0)
    unit: str = Field(min_length=1, max_length=32)
    experimental_unit_id: str | None = Field(default=None, max_length=150)
    experimental_unit_type: str | None = Field(default=None, max_length=100)

    @field_validator(
        "organism_id",
        "parent_colony_id",
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

    @field_validator("observed_at", mode="before")
    @classmethod
    def explicit_calendar_timestamp(cls, value: object) -> object:
        # Pydantic otherwise converts Unix seconds (including numeric strings)
        # into UTC datetimes. That would silently invent acquisition-time
        # semantics for an unverified scientific observation.
        if isinstance(value, datetime):
            return value
        if not isinstance(value, str) or not re.match(r"^\d{4}-\d{2}-\d{2}[Tt ]", value.strip()):
            raise ValueError("Observation time must be an explicit ISO 8601 calendar timestamp")
        return value

    @field_validator("observed_at")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Observation time must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("value", mode="before")
    @classmethod
    def reject_boolean_measurements(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("Observation measurement must be numeric, not Boolean")
        if not isinstance(value, (int, float)):
            raise ValueError("Observation measurement must be a JSON number, not coerced")
        return value

    @field_validator("value")
    @classmethod
    def finite_value(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("Observation values must be finite")
        return value


class LongitudinalAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observations: list[MonitoringObservation] = Field(min_length=2, max_length=10000)
    experimental_unit_type: str | None = Field(default=None, max_length=100)
    expected_organism_ids_by_unit: dict[str, list[str]] | None = Field(
        default=None, max_length=10000
    )
    expected_sampling_dates_by_unit: dict[str, list[date]] | None = Field(
        default=None, max_length=10000
    )

    @field_validator("expected_sampling_dates_by_unit", mode="before")
    @classmethod
    def require_explicit_iso_sampling_dates(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("Expected sampling calendar must map unit IDs to UTC dates")
        for dates in value.values():
            if not isinstance(dates, list) or any(
                not isinstance(day, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) is None
                for day in dates
            ):
                raise ValueError("Expected sampling dates must be explicit ISO YYYY-MM-DD strings")
        return value

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
        if declared:
            canonical = canonical_declared_unit_type(declared)
            if canonical is None:
                raise ValueError("Observations declare conflicting experimental unit types")
            if self.experimental_unit_type is not None and not ecological_unit_types_equivalent(
                self.experimental_unit_type, canonical
            ):
                raise ValueError("Request and observations disagree on experimental unit type")
            # An explicit request label is retained; mixed aliases without one
            # resolve to a deterministic biological level (e.g. "tank").
            self.experimental_unit_type = self.experimental_unit_type or canonical
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
    expected_organism_count: int | None = Field(default=None, ge=1)
    unobserved_organism_ids: list[str] = Field(default_factory=list)
    observed_sampling_dates_by_organism: dict[str, list[date]] = Field(default_factory=dict)
    discordant_sampling_dates: bool = False
    expected_sampling_dates: list[date] = Field(default_factory=list)
    missing_scheduled_dates_by_organism: dict[str, list[date]] = Field(default_factory=dict)
    eligible_for_summary: bool
    exclusion_reason: (
        Literal[
            "missing_followup",
            "nonmatching_sampling_window",
            "missing_expected_organisms",
            "missing_scheduled_observations",
        ]
        | None
    ) = None


class PlannedSamplingEffort(BaseModel):
    """Scheduled organism-visits per declared unit/metric, not a survival estimate."""

    experimental_unit_id: str
    metric_name: str
    planned_sampling_date_count: int = Field(ge=2)
    expected_organism_count: int = Field(ge=1)
    expected_organism_visits: int = Field(ge=1)
    observed_organism_visits: int = Field(ge=0)
    missing_organism_visits: int = Field(ge=0)
    observation_coverage_fraction: float = Field(ge=0, le=1)
    expected_roster_supplied: bool = False


class PlannedSamplingDateCoverage(BaseModel):
    """Per-UTC-visit organism coverage, not a mortality or abundance estimate."""

    experimental_unit_id: str
    metric_name: str
    sampling_date: date
    expected_organism_count: int = Field(ge=1)
    observed_organism_count: int = Field(ge=0)
    observed_organism_ids: list[str] = Field(default_factory=list)
    missing_organism_ids: list[str] = Field(default_factory=list)
    observation_coverage_fraction: float = Field(ge=0, le=1)
    expected_roster_supplied: bool = False


class ExcludedExperimentalUnit(BaseModel):
    experimental_unit_id: str
    metric_name: str
    reason: Literal[
        "missing_followup",
        "nonmatching_sampling_window",
        "missing_expected_organisms",
        "missing_scheduled_observations",
    ]


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
    expected_roster_supplied: bool = False
    expected_sampling_schedule_supplied: bool = False
    cross_unit_shared_parent_colony_ids: list[str] = Field(default_factory=list)
    unit_summaries: list[ExperimentalUnitSummary] = Field(default_factory=list)
    population_summaries: list[PopulationUnitSummary] = Field(default_factory=list)
    excluded_units: list[ExcludedExperimentalUnit] = Field(default_factory=list)
    unit_coverage: list[ExperimentalUnitCoverage] = Field(default_factory=list)
    planned_sampling_effort: list[PlannedSamplingEffort] = Field(default_factory=list)
    planned_sampling_date_coverage: list[PlannedSamplingDateCoverage] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
