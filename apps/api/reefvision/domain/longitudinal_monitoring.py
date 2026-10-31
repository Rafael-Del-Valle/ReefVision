"""Conservative first/final repeated-organism comparisons (ReefVision 1.2)."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date

from reefvision.domain.ecology_expected_roster import validate_expected_roster
from reefvision.domain.ecology_lineage_policy import (
    cross_unit_shared_parent_colony_ids,
    validate_declared_lineage,
)
from reefvision.domain.ecology_unit_coverage import (
    audit_unit_coverage,
    summarize_planned_sampling_dates,
    summarize_planned_sampling_effort,
)
from reefvision.domain.errors import ValidationError
from reefvision.domain.population_unit_summaries import summarize_population_units
from reefvision.domain.scientific_input_provenance import scientific_input_provenance
from reefvision.domain.scientific_mean import finite_descriptive_mean
from reefvision.schemas.longitudinal_monitoring import (
    ExcludedExperimentalUnit,
    ExperimentalUnitCoverage,
    ExperimentalUnitSummary,
    LongitudinalAnalysisRequest,
    LongitudinalAnalysisResponse,
    LongitudinalChange,
    MonitoringObservation,
    PlannedSamplingDateCoverage,
    PlannedSamplingEffort,
)


def _summarize_experimental_units(
    request: LongitudinalAnalysisRequest,
    grouped: dict[tuple[str, str], list[MonitoringObservation]],
    changes: list[LongitudinalChange],
    expected_by_unit: dict[str, list[str]],
    schedule_by_unit: dict[str, list[date]],
) -> tuple[int | None, list[ExperimentalUnitSummary], list[ExcludedExperimentalUnit]]:
    """Summarize organisms *within* declared units, never as independent units.

    Exclude an entire unit/metric when a constituent organism is missing a
    follow-up or when its first/last sampling window differs. No p-values,
    treatment contrasts, or between-unit pooling are calculated here.
    """
    unit_type = request.experimental_unit_type
    if unit_type is None:
        if any(obs.experimental_unit_id is not None for obs in request.observations):
            raise ValidationError(
                "experimental_unit_type is required when experimental_unit_id is supplied"
            )
        return None, [], []

    memberships: dict[str, str] = {}
    for obs in request.observations:
        if obs.experimental_unit_id is None:
            raise ValidationError(
                "Every observation needs experimental_unit_id for unit-level summaries"
            )
        previous = memberships.setdefault(obs.organism_id, obs.experimental_unit_id)
        if previous != obs.experimental_unit_id:
            raise ValidationError(
                f"Organism {obs.organism_id!r} changes experimental units; "
                "split identities or correct the study design"
            )

    # Never mix physical units across organisms for a metric, even when they
    # belong to different experimental units.
    units_by_metric: dict[str, set[str]] = defaultdict(set)
    for obs in request.observations:
        units_by_metric[obs.metric_name].add(obs.unit)
    for metric, units in units_by_metric.items():
        if len(units) > 1:
            raise ValidationError(
                f"Experimental-unit summary for {metric!r} mixes measurement units"
            )

    series_by_unit: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for organism_id, metric_name in grouped:
        series_by_unit[(memberships[organism_id], metric_name)].append((organism_id, metric_name))
    completed = {(item.organism_id, item.metric_name): item for item in changes}
    summaries: list[ExperimentalUnitSummary] = []
    excluded: list[ExcludedExperimentalUnit] = []
    for (unit_id, metric), keys in sorted(series_by_unit.items()):
        observed_organisms = {organism_id for organism_id, _ in keys}
        if set(expected_by_unit.get(unit_id, ())) - observed_organisms:
            excluded.append(
                ExcludedExperimentalUnit(
                    experimental_unit_id=unit_id,
                    metric_name=metric,
                    reason="missing_expected_organisms",
                )
            )
            continue
        # A singleton can also have missing scheduled visits. Classify those
        # visits before the generic missing-followup check, so QC reports the
        # actionable calendar gaps without inventing death or zero abundance.
        scheduled = set(schedule_by_unit.get(unit_id, ()))
        if scheduled and any(
            scheduled - {row.observed_at.date() for row in grouped[key]} for key in keys
        ):
            excluded.append(
                ExcludedExperimentalUnit(
                    experimental_unit_id=unit_id,
                    metric_name=metric,
                    reason="missing_scheduled_observations",
                )
            )
            continue
        if any(key not in completed for key in keys):
            excluded.append(
                ExcludedExperimentalUnit(
                    experimental_unit_id=unit_id,
                    metric_name=metric,
                    reason="missing_followup",
                )
            )
            continue
        series = [completed[key] for key in sorted(keys)]
        # Fragments imaged at different hours of the same UTC sampling dates
        # share a biological sampling window; their photographs are not
        # independent time points. Each organism still retains its exact
        # timestamps for change-per-day calculations.
        windows = {(item.first_observed_at.date(), item.last_observed_at.date()) for item in series}
        if len(windows) != 1:
            excluded.append(
                ExcludedExperimentalUnit(
                    experimental_unit_id=unit_id,
                    metric_name=metric,
                    reason="nonmatching_sampling_window",
                )
            )
            continue
        # Preserve the full within-date acquisition envelope rather than
        # arbitrarily selecting the timestamps of one organism.
        baseline_at = min(item.first_observed_at for item in series)
        final_at = max(item.last_observed_at for item in series)
        mean_change = finite_descriptive_mean(item.absolute_change for item in series)
        mean_rate = finite_descriptive_mean(item.change_per_day for item in series)
        if not all(math.isfinite(v) for v in (mean_change, mean_rate)):
            raise ValidationError("Experimental-unit summary is not finite")
        summaries.append(
            ExperimentalUnitSummary(
                experimental_unit_id=unit_id,
                metric_name=metric,
                unit=series[0].unit,
                organism_count=len(series),
                baseline_at=baseline_at,
                final_at=final_at,
                mean_absolute_change=mean_change,
                mean_change_per_day=mean_rate,
            )
        )
    return len(set(memberships.values())), summaries, excluded


def analyze_longitudinal(
    request: LongitudinalAnalysisRequest,
) -> LongitudinalAnalysisResponse:
    """Compare endpoints without treating images or fragments as independent replicates.

    This is an exploratory calculator for caller-supplied measurements, NOT a read of
    verified ReefVision annotations. It does not estimate survival or significance.
    """
    validate_declared_lineage(
        request.observations, experimental_unit_type=request.experimental_unit_type
    )
    expected_by_unit = validate_expected_roster(
        request.observations,
        request.expected_organism_ids_by_unit,
        experimental_unit_type=request.experimental_unit_type,
    )
    schedule_by_unit = _validate_sampling_schedule(request)
    grouped: dict[tuple[str, str], list[MonitoringObservation]] = defaultdict(list)
    used_sources: set[str] = set()
    for obs in request.observations:
        if obs.source_record_id in used_sources:
            raise ValidationError("Each source_record_id must identify one unique observation")
        used_sources.add(obs.source_record_id)
        grouped[(obs.organism_id, obs.metric_name)].append(obs)

    changes: list[LongitudinalChange] = []
    incomplete = 0
    for (organism_id, metric_name), observations in sorted(grouped.items()):
        units = {obs.unit for obs in observations}
        if len(units) != 1:
            raise ValidationError(
                f"Repeated measurements for {organism_id!r}/{metric_name!r} "
                "mix units; normalize explicitly before comparison"
            )
        ordered = sorted(observations, key=lambda item: item.observed_at)
        if len({item.observed_at for item in ordered}) != len(ordered):
            raise ValidationError(
                f"Ambiguous simultaneous measurements for {organism_id!r}/{metric_name!r}"
            )
        # Multiple photographs on one UTC sampling date are technical
        # replicates, not separate longitudinal biological time points.
        # Require an explicit reviewed aggregation upstream rather than
        # arbitrarily choosing the first or last photograph.
        utc_sampling_dates = [item.observed_at.date() for item in ordered]
        if len(set(utc_sampling_dates)) != len(utc_sampling_dates):
            raise ValidationError(
                f"Multiple observations on the same UTC sampling date for "
                f"{organism_id!r}/{metric_name!r}; resolve technical replicates "
                "before longitudinal analysis"
            )
        if len(ordered) < 2:
            incomplete += 1
            continue
        first, last = ordered[0], ordered[-1]
        elapsed_days = (last.observed_at - first.observed_at).total_seconds() / 86400.0
        if elapsed_days <= 0:
            raise ValidationError("Repeated measurements must span positive elapsed time")
        difference = last.value - first.value
        percent = difference / first.value * 100 if first.value > 0 else None
        rate = difference / elapsed_days
        if any(not math.isfinite(value) for value in (difference, rate)):
            raise ValidationError("Computed change is not finite")
        if percent is not None and not math.isfinite(percent):
            raise ValidationError("Computed percentage change is not finite")
        changes.append(
            LongitudinalChange(
                organism_id=organism_id,
                metric_name=metric_name,
                unit=first.unit,
                first_observed_at=first.observed_at,
                last_observed_at=last.observed_at,
                baseline_source_record_id=first.source_record_id,
                final_source_record_id=last.source_record_id,
                initial_value=first.value,
                final_value=last.value,
                absolute_change=difference,
                percent_change=percent,
                elapsed_days=elapsed_days,
                change_per_day=rate,
                observation_count=len(ordered),
            )
        )
    independent_unit_count, unit_summaries, excluded_units = _summarize_experimental_units(
        request, grouped, changes, expected_by_unit, schedule_by_unit
    )
    unit_coverage = (
        [
            ExperimentalUnitCoverage.model_validate(row)
            for row in audit_unit_coverage(
                grouped,
                changes,
                unit_summaries,
                excluded_units,
                expected_by_unit=expected_by_unit,
                schedule_by_unit=schedule_by_unit,
            )
        ]
        if independent_unit_count is not None
        else []
    )
    population_summaries = summarize_population_units(unit_summaries)
    planned_sampling_effort = [
        PlannedSamplingEffort.model_validate(row)
        for row in summarize_planned_sampling_effort(unit_coverage)
    ]
    return LongitudinalAnalysisResponse(
        observation_count=len(request.observations),
        analysis_provenance=scientific_input_provenance(
            algorithm_version=(
                "ecology-longitudinal-0012"
                if request.expected_sampling_dates_by_unit is not None
                else "ecology-longitudinal-0008"
            ),
            records=request.observations,
            parameters={
                "experimental_unit_type": request.experimental_unit_type,
                "expected_organism_ids_by_unit": (
                    expected_by_unit if request.expected_organism_ids_by_unit is not None else None
                ),
                **(
                    {
                        "expected_sampling_dates_by_unit": {
                            unit_id: [day.isoformat() for day in dates]
                            for unit_id, dates in schedule_by_unit.items()
                        }
                    }
                    if request.expected_sampling_dates_by_unit is not None
                    else {}
                ),
            },
            source_record_ids=(obs.source_record_id for obs in request.observations),
        ),
        evaluated_series_count=len(changes),
        incomplete_series_count=incomplete,
        changes=changes,
        experimental_unit_type=request.experimental_unit_type,
        independent_unit_count=independent_unit_count,
        expected_roster_supplied=request.expected_organism_ids_by_unit is not None,
        expected_sampling_schedule_supplied=request.expected_sampling_dates_by_unit is not None,
        cross_unit_shared_parent_colony_ids=cross_unit_shared_parent_colony_ids(
            request.observations
        ),
        unit_summaries=unit_summaries,
        population_summaries=population_summaries,
        excluded_units=excluded_units,
        unit_coverage=unit_coverage,
        planned_sampling_effort=planned_sampling_effort,
        planned_sampling_date_coverage=[
            PlannedSamplingDateCoverage.model_validate(row)
            for row in summarize_planned_sampling_dates(unit_coverage)
        ],
        limitations=[
            "Caller-supplied observations are not verified against project data or calibration.",
            "Parent-colony identity and experimental units are declared, not authenticated.",
            "Optional expected organism rosters are caller-supplied and unverified; "
            "unobserved organisms are not deaths or zero counts.",
            "Changes compare the first and last sampling dates; "
            "no statistical significance is inferred.",
            "Organisms are the reporting unit; observations are not pooled "
            "as independent replicates.",
            "Experimental-unit means are descriptive only, require an explicitly declared "
            "sampling unit and matching organism-level UTC sampling-date windows, and exclude "
            "units with missing follow-up; they are not independent hypothesis tests.",
            "Cross-unit summaries weight eligible units equally and stratify by UTC dates; "
            "no population inference or significance is claimed.",
            "Declared planned sampling dates exclude units with missing visits; "
            "missing visits do not establish mortality, absence or zero abundance.",
            "Per-visit UTC sampling coverage identifies missing organism observations, not "
            "mortality, absence or zero abundance.",
            "Planned organism-visit coverage counts missing measurements, not mortality; "
            "without a roster, completely unobserved organisms cannot enter its denominator.",
            "Different intermediate observation dates within a unit are disclosed as QC; "
            "they do not establish missing scheduled visits or invalidate endpoint-only means.",
        ],
    )


def _validate_sampling_schedule(
    request: LongitudinalAnalysisRequest,
) -> dict[str, list[date]]:
    """Normalize optional caller-declared UTC visit calendars; never authenticate them."""
    declared = request.expected_sampling_dates_by_unit
    if declared is None:
        return {}
    if not declared or request.experimental_unit_type is None:
        raise ValidationError("Expected sampling schedule requires a unit type and nonempty dates")
    units = {row.experimental_unit_id for row in request.observations}
    if None in units:
        raise ValidationError("Expected sampling schedule requires unit IDs on all observations")
    if set(declared) != units:
        raise ValidationError("Expected sampling schedule must cover exactly the observed units")
    canonical: dict[str, list[date]] = {}
    total = 0
    for unit_id, dates in sorted(declared.items()):
        if not unit_id or unit_id.strip() != unit_id:
            raise ValidationError("Expected sampling schedule unit ID cannot be blank")
        if len(dates) < 2:
            raise ValidationError("Expected sampling schedule needs at least two UTC dates")
        if len(dates) != len(set(dates)):
            raise ValidationError("Expected sampling schedule contains duplicate UTC dates")
        total += len(dates)
        if total > 10000:
            raise ValidationError("Expected sampling schedule exceeds 10000 dates")
        canonical[unit_id] = sorted(dates)
    for row in request.observations:
        observed_unit_id = row.experimental_unit_id
        # The earlier whole-request check validates the declared unit set;
        # narrow the optional ID explicitly before indexing a typed calendar.
        if observed_unit_id is None:
            raise ValidationError(
                "Expected sampling schedule requires unit IDs on all observations"
            )
        if row.observed_at.date() not in canonical[observed_unit_id]:
            raise ValidationError("Observed UTC date is outside the expected sampling schedule")
    return canonical
