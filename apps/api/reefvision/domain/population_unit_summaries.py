"""One descriptive vote per eligible experimental unit, never per photograph."""

from __future__ import annotations

from collections import defaultdict

from reefvision.domain.errors import ValidationError
from reefvision.domain.scientific_mean import finite_descriptive_mean
from reefvision.schemas.longitudinal_monitoring import (
    ExperimentalUnitSummary,
    PopulationUnitSummary,
)


def summarize_population_units(
    unit_summaries: list[ExperimentalUnitSummary],
) -> list[PopulationUnitSummary]:
    """Keep incompatible metric/unit/UTC-date windows in separate strata.

    Caller-declared independent units are not authenticated to a study design.
    No inferential statistics, population estimates or survival rates are made.
    """
    grouped: dict[tuple[str, str, str, str], list[ExperimentalUnitSummary]] = defaultdict(list)
    for row in unit_summaries:
        key = (
            row.metric_name,
            row.unit,
            row.baseline_at.date().isoformat(),
            row.final_at.date().isoformat(),
        )
        grouped[key].append(row)

    results: list[PopulationUnitSummary] = []
    for (metric, unit, baseline_date, final_date), members in sorted(grouped.items()):
        members.sort(key=lambda row: row.experimental_unit_id)
        ids = [row.experimental_unit_id for row in members]
        if len(ids) != len(set(ids)):
            raise ValidationError("An experimental unit cannot contribute twice to a stratum")
        results.append(
            PopulationUnitSummary(
                metric_name=metric,
                unit=unit,
                baseline_date=baseline_date,
                final_date=final_date,
                independent_unit_count=len(ids),
                contributing_organism_count=sum(row.organism_count for row in members),
                experimental_unit_ids=ids,
                mean_unit_absolute_change=finite_descriptive_mean(
                    row.mean_absolute_change for row in members
                ),
                mean_unit_change_per_day=finite_descriptive_mean(
                    row.mean_change_per_day for row in members
                ),
            )
        )
    return results
