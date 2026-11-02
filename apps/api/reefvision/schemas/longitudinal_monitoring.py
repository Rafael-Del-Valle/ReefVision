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
    require_unique_ecological_organism_key_spellings,
)
from reefvision.domain.experimental_unit_policy import require_ecological_unit_type
from reefvision.domain.scientific_mean import finite_descriptive_mean
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

    @model_validator(mode="after")
    def reconcile_visit_denominator(self) -> PlannedSamplingEffort:
        """Prevent persisted effort totals from inventing biological visits."""
        expected = self.planned_sampling_date_count * self.expected_organism_count
        if self.expected_organism_visits != expected:
            raise ValueError("Planned organism-visit denominator does not reconcile")
        if self.observed_organism_visits + self.missing_organism_visits != expected:
            raise ValueError("Planned organism-visit counts do not reconcile")
        if not math.isclose(
            self.observation_coverage_fraction,
            self.observed_organism_visits / expected,
            rel_tol=1e-9,
            abs_tol=1e-12,
        ):
            raise ValueError("Planned organism-visit coverage fraction does not reconcile")
        return self


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

    @model_validator(mode="after")
    def reconcile_visit_roster(self) -> PlannedSamplingDateCoverage:
        """Each planned organism has exactly one observed or missing status."""
        observed = self.observed_organism_ids
        missing = self.missing_organism_ids
        if (
            len(observed) != len(set(observed))
            or len(missing) != len(set(missing))
            or set(observed).intersection(missing)
        ):
            raise ValueError("Planned visit organism IDs must be unique and disjoint")
        if self.observed_organism_count != len(observed):
            raise ValueError("Planned visit observed organism count does not reconcile")
        if len(observed) + len(missing) != self.expected_organism_count:
            raise ValueError("Planned visit expected organism count does not reconcile")
        if not math.isclose(
            self.observation_coverage_fraction,
            len(observed) / self.expected_organism_count,
            rel_tol=1e-9,
            abs_tol=1e-12,
        ):
            raise ValueError("Planned visit coverage fraction does not reconcile")
        return self


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

    @model_validator(mode="after")
    def reject_aliases_in_persisted_organism_rosters(self) -> LongitudinalAnalysisResponse:
        """Do not replay alias-split organism denominators as biological samples."""
        identifiers = [row.organism_id for row in self.changes]
        identifiers.extend(
            organism
            for coverage in self.unit_coverage
            for organism in coverage.observed_sampling_dates_by_organism
        )
        # A persisted roster also contains individuals never observed.
        # Check all denominator-bearing identities, not only source-linked
        # changes: a forged missing or planned-visit alias must not inflate
        # the apparent number of biological individuals on replay.
        for coverage in self.unit_coverage:
            identifiers.extend(coverage.missing_organism_ids)
            identifiers.extend(coverage.unobserved_organism_ids)
            identifiers.extend(coverage.missing_scheduled_dates_by_organism)
        for visit in self.planned_sampling_date_coverage:
            identifiers.extend(visit.observed_organism_ids)
            identifiers.extend(visit.missing_organism_ids)
        try:
            require_unique_ecological_organism_key_spellings(identifiers)
        except ValueError as exc:
            raise ValueError(
                "Longitudinal persisted organism IDs differ only by case or Unicode compatibility"
            ) from exc
        # A saved result cannot inflate biological units by relabeling a
        # tank/colony across its metric, coverage, or population records.
        unit_ids = [row.experimental_unit_id for row in self.unit_summaries]
        unit_ids.extend(row.experimental_unit_id for row in self.excluded_units)
        unit_ids.extend(row.experimental_unit_id for row in self.unit_coverage)
        unit_ids.extend(row.experimental_unit_id for row in self.planned_sampling_effort)
        unit_ids.extend(row.experimental_unit_id for row in self.planned_sampling_date_coverage)
        unit_ids.extend(
            unit_id
            for population in self.population_summaries
            for unit_id in population.experimental_unit_ids
        )
        try:
            require_unique_ecological_organism_key_spellings(unit_ids)
        except ValueError as exc:
            raise ValueError(
                "Longitudinal persisted experimental unit IDs differ only by case "
                "or Unicode compatibility"
            ) from exc
        return self

    @model_validator(mode="after")
    def reconcile_persisted_unit_means_with_changes(self) -> LongitudinalAnalysisResponse:
        """Prevent re-signed unit means from contradicting organism endpoints.

        Only reconcile when both optional historical sections exist. Organism
        membership comes from the separate per-unit coverage audit, not from
        a caller's claim that fragments are independent replicates.
        """
        if not self.unit_coverage or not self.unit_summaries:
            return self

        coverage_by_key = {
            (row.experimental_unit_id, row.metric_name): row
            for row in self.unit_coverage
        }
        if len(coverage_by_key) != len(self.unit_coverage):
            raise ValueError("Unit summary duplicate coverage records")
        changes_by_key = {(row.organism_id, row.metric_name): row for row in self.changes}
        if len(changes_by_key) != len(self.changes):
            raise ValueError("Unit summary duplicate organism change records")
        summary_keys = {
            (row.experimental_unit_id, row.metric_name) for row in self.unit_summaries
        }
        eligible_keys = {
            key for key, coverage in coverage_by_key.items() if coverage.eligible_for_summary
        }
        if len(summary_keys) != len(self.unit_summaries) or summary_keys != eligible_keys:
            raise ValueError("Unit summary eligibility does not reconcile with coverage")

        for summary in self.unit_summaries:
            coverage = coverage_by_key[(summary.experimental_unit_id, summary.metric_name)]
            organism_ids = list(coverage.observed_sampling_dates_by_organism)
            if (
                summary.organism_count != len(organism_ids)
                or coverage.observed_organism_count != len(organism_ids)
                or coverage.complete_organism_count != len(organism_ids)
                or coverage.missing_organism_ids
                or coverage.unobserved_organism_ids
            ):
                raise ValueError("Unit summary organism denominator does not reconcile")
            series = [
                changes_by_key.get((organism_id, summary.metric_name))
                for organism_id in organism_ids
            ]
            if any(change is None for change in series):
                raise ValueError("Unit summary lacks a completed organism change")
            completed = [change for change in series if change is not None]
            if any(change.unit != summary.unit for change in completed):
                raise ValueError("Unit summary measurement units disagree with organism changes")
            windows = {
                (change.first_observed_at.date(), change.last_observed_at.date())
                for change in completed
            }
            if len(windows) != 1:
                raise ValueError("Unit summary organism sampling windows do not reconcile")
            if (
                summary.baseline_at != min(change.first_observed_at for change in completed)
                or summary.final_at != max(change.last_observed_at for change in completed)
            ):
                raise ValueError("Unit summary endpoint timestamps do not reconcile")
            expected_change = finite_descriptive_mean(
                change.absolute_change for change in completed
            )
            expected_rate = finite_descriptive_mean(
                change.change_per_day for change in completed
            )
            if not (
                math.isfinite(summary.mean_absolute_change)
                and math.isfinite(summary.mean_change_per_day)
                and math.isclose(
                    summary.mean_absolute_change,
                    expected_change,
                    rel_tol=1e-9,
                    abs_tol=1e-12,
                )
                and math.isclose(
                    summary.mean_change_per_day,
                    expected_rate,
                    rel_tol=1e-9,
                    abs_tol=1e-12,
                )
            ):
                raise ValueError("Unit summary means disagree with organism changes")
        return self

    @model_validator(mode="after")
    def reconcile_persisted_population_units(self) -> LongitudinalAnalysisResponse:
        """A saved population stratum must give each eligible unit one vote.

        Legacy artifacts with only one optional summary section remain readable.
        This is internal consistency checking, not source-data authentication.
        """
        if not self.unit_summaries or not self.population_summaries:
            return self

        strata: dict[tuple[str, str, date, date], list[ExperimentalUnitSummary]] = {}
        unit_keys: set[tuple[str, str]] = set()
        for unit in self.unit_summaries:
            unit_key = (unit.experimental_unit_id, unit.metric_name)
            if unit_key in unit_keys:
                raise ValueError("Population summary duplicate experimental unit/metric")
            unit_keys.add(unit_key)
            if unit.organism_count < 1:
                raise ValueError("Population summary unit must contain an organism")
            stratum = (
                unit.metric_name,
                unit.unit,
                unit.baseline_at.date(),
                unit.final_at.date(),
            )
            strata.setdefault(stratum, []).append(unit)

        if len(self.population_summaries) != len(strata):
            raise ValueError("Population summary strata do not reconcile")
        seen: set[tuple[str, str, date, date]] = set()
        for population in self.population_summaries:
            key = (
                population.metric_name,
                population.unit,
                population.baseline_date,
                population.final_date,
            )
            if key in seen or key not in strata:
                raise ValueError("Population summary strata do not reconcile")
            seen.add(key)
            members = strata[key]
            unit_ids = sorted(member.experimental_unit_id for member in members)
            if len(set(unit_ids)) != len(unit_ids) or population.experimental_unit_ids != unit_ids:
                raise ValueError("Population summary experimental unit roster does not reconcile")
            if population.independent_unit_count != len(unit_ids):
                raise ValueError("Population summary independent unit count does not reconcile")
            if population.contributing_organism_count != sum(
                member.organism_count for member in members
            ):
                raise ValueError("Population summary contributing organisms do not reconcile")
            expected_change = finite_descriptive_mean(
                member.mean_absolute_change for member in members
            )
            expected_rate = finite_descriptive_mean(
                member.mean_change_per_day for member in members
            )
            if not (
                math.isfinite(population.mean_unit_absolute_change)
                and math.isfinite(population.mean_unit_change_per_day)
                and math.isclose(
                    population.mean_unit_absolute_change,
                    expected_change,
                    rel_tol=1e-9,
                    abs_tol=1e-12,
                )
                and math.isclose(
                    population.mean_unit_change_per_day,
                    expected_rate,
                    rel_tol=1e-9,
                    abs_tol=1e-12,
                )
            ):
                raise ValueError("Population summary unit-weighted means do not reconcile")
        return self

    @model_validator(mode="after")
    def reconcile_persisted_planned_visits(self) -> LongitudinalAnalysisResponse:
        """Cross-check per-date rosters against persisted unit-level effort.

        Legacy artifacts may contain only one of these optional result sections;
        when both exist, neither can contradict the other.
        """
        if not self.planned_sampling_effort or not self.planned_sampling_date_coverage:
            return self

        effort_by_key: dict[tuple[str, str], PlannedSamplingEffort] = {}
        for effort in self.planned_sampling_effort:
            key = (effort.experimental_unit_id, effort.metric_name)
            if key in effort_by_key:
                raise ValueError("Planned visit duplicate experimental-unit effort")
            effort_by_key[key] = effort

        visits_by_key: dict[tuple[str, str], list[PlannedSamplingDateCoverage]] = {}
        for visit in self.planned_sampling_date_coverage:
            key = (visit.experimental_unit_id, visit.metric_name)
            visits_by_key.setdefault(key, []).append(visit)
        if set(visits_by_key) != set(effort_by_key):
            raise ValueError("Planned visit units do not reconcile with effort")

        for key, effort in effort_by_key.items():
            visits = visits_by_key[key]
            dates = {visit.sampling_date for visit in visits}
            if len(visits) != effort.planned_sampling_date_count or len(dates) != len(visits):
                raise ValueError("Planned visit dates do not reconcile with effort")
            if any(
                visit.expected_organism_count != effort.expected_organism_count
                or visit.expected_roster_supplied != effort.expected_roster_supplied
                for visit in visits
            ):
                raise ValueError("Planned visit roster metadata does not reconcile")
            rosters = [
                set(visit.observed_organism_ids) | set(visit.missing_organism_ids)
                for visit in visits
            ]
            if any(roster != rosters[0] for roster in rosters[1:]):
                raise ValueError("Planned visit organism roster changes between dates")
            if (
                sum(visit.observed_organism_count for visit in visits)
                != effort.observed_organism_visits
                or sum(len(visit.missing_organism_ids) for visit in visits)
                != effort.missing_organism_visits
            ):
                raise ValueError("Planned visit totals do not reconcile with effort")
        return self

    @model_validator(mode="after")
    def reconcile_persisted_visits_with_unit_coverage(self) -> LongitudinalAnalysisResponse:
        """Reconcile per-date identities with the organism-level sampling audit.

        Legacy artifacts containing only one optional section remain readable.
        """
        if not self.unit_coverage or not self.planned_sampling_date_coverage:
            return self

        coverage_by_key: dict[tuple[str, str], ExperimentalUnitCoverage] = {}
        for coverage in self.unit_coverage:
            key = (coverage.experimental_unit_id, coverage.metric_name)
            if key in coverage_by_key:
                raise ValueError("Planned visit duplicate unit coverage")
            coverage_by_key[key] = coverage

        visits_by_key: dict[tuple[str, str], list[PlannedSamplingDateCoverage]] = {}
        for visit in self.planned_sampling_date_coverage:
            key = (visit.experimental_unit_id, visit.metric_name)
            visits_by_key.setdefault(key, []).append(visit)
        scheduled_keys = {
            key for key, coverage in coverage_by_key.items() if coverage.expected_sampling_dates
        }
        if set(visits_by_key) != scheduled_keys:
            raise ValueError("Planned visit units disagree with unit coverage")

        for key, visits in visits_by_key.items():
            coverage = coverage_by_key[key]
            scheduled_dates = set(coverage.expected_sampling_dates)
            if (
                len(visits) != len(scheduled_dates)
                or {visit.sampling_date for visit in visits} != scheduled_dates
            ):
                raise ValueError("Planned visit dates disagree with unit coverage")
            observed_dates = coverage.observed_sampling_dates_by_organism
            expected_ids = set(observed_dates) | set(coverage.unobserved_organism_ids)
            expected_count = coverage.expected_organism_count or coverage.observed_organism_count
            if len(expected_ids) != expected_count:
                raise ValueError("Planned visit roster disagrees with unit coverage")
            if any(set(dates) - scheduled_dates for dates in observed_dates.values()):
                raise ValueError("Planned visit observation dates exceed unit coverage schedule")
            for visit in visits:
                observed_ids = {
                    organism
                    for organism, dates in observed_dates.items()
                    if visit.sampling_date in dates
                }
                if set(visit.observed_organism_ids) != observed_ids:
                    raise ValueError("Planned visit observed roster disagrees with unit coverage")
                if set(visit.missing_organism_ids) != expected_ids - observed_ids:
                    raise ValueError("Planned visit missing roster disagrees with unit coverage")
                if visit.expected_roster_supplied != (coverage.expected_organism_count is not None):
                    raise ValueError("Planned visit roster flag disagrees with unit coverage")
        return self
