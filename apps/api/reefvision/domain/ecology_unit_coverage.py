"""Auditable denominators for longitudinal ecological experimental units.

Declared units remain unverified; this module reports descriptive coverage,
never independent experimental replication or statistical significance.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from typing import Any


def audit_unit_coverage(
    grouped: Mapping[tuple[str, str], Sequence[Any]],
    changes: Iterable[Any],
    unit_summaries: Iterable[Any],
    excluded_units: Iterable[Any],
    *,
    expected_by_unit: Mapping[str, Sequence[str]] | None = None,
    schedule_by_unit: Mapping[str, Sequence[date]] | None = None,
) -> list[dict[str, Any]]:
    """Reconcile one coverage record per declared experimental unit and metric."""
    changes = list(changes)
    completed = {(row.organism_id, row.metric_name) for row in changes}
    if len(completed) != len(changes):
        raise ValueError("Duplicate completed organism/metric series")
    if not completed.issubset(grouped):
        raise ValueError("Completed change has no corresponding observed series")
    by_unit_metric: dict[tuple[str, str], list[tuple[str, bool]]] = defaultdict(list)
    organism_memberships: dict[str, str] = {}
    sampling_dates: dict[tuple[str, str], dict[str, list[date]]] = defaultdict(dict)
    for (organism_id, metric_name), observations in grouped.items():
        if not observations:
            raise ValueError("An organism/metric series cannot be empty")
        ids = {row.experimental_unit_id for row in observations}
        if len(ids) != 1 or None in ids:
            raise ValueError("Unit coverage requires a stable declared unit per organism")
        unit_id = next(iter(ids))
        prior_unit = organism_memberships.setdefault(organism_id, unit_id)
        if prior_unit != unit_id:
            raise ValueError("An organism cannot change experimental units between metrics")
        if (organism_id, metric_name) in completed and len(observations) < 2:
            raise ValueError("Completed series requires repeated observations")
        key = (unit_id, metric_name)
        sampling_dates[key][organism_id] = sorted({row.observed_at.date() for row in observations})
        by_unit_metric[key].append((organism_id, (organism_id, metric_name) in completed))

    summaries = list(unit_summaries)
    eligible_rows = [(row.experimental_unit_id, row.metric_name) for row in summaries]
    excluded_rows = [
        (row.experimental_unit_id, row.metric_name, row.reason) for row in excluded_units
    ]
    if len(eligible_rows) != len(set(eligible_rows)):
        raise ValueError("Duplicate eligible experimental-unit decision")
    excluded_keys = [(unit_id, metric) for unit_id, metric, _ in excluded_rows]
    if len(excluded_keys) != len(set(excluded_keys)):
        raise ValueError("Duplicate excluded experimental-unit decision")
    eligible = set(eligible_rows)
    for row in summaries:
        key = (row.experimental_unit_id, row.metric_name)
        count = getattr(row, "organism_count", None)
        if count is not None and count != len(by_unit_metric.get(key, ())):
            raise ValueError("Eligible experimental-unit organism count disagrees with coverage")
    exclusions = {(unit_id, metric): reason for unit_id, metric, reason in excluded_rows}
    if eligible.intersection(exclusions):
        raise ValueError("A unit/metric cannot be eligible and excluded simultaneously")
    if eligible.union(exclusions) != set(by_unit_metric):
        raise ValueError("Unit coverage does not reconcile with analysis decisions")

    results: list[dict[str, Any]] = []
    expected_by_unit = expected_by_unit or {}
    schedule_by_unit = schedule_by_unit or {}
    for (unit_id, metric), flags in sorted(by_unit_metric.items()):
        observed_ids = {organism_id for organism_id, _ in flags}
        unobserved_ids = sorted(set(expected_by_unit.get(unit_id, ())) - observed_ids)
        complete = sum(is_complete for _, is_complete in flags)
        missing_ids = sorted(organism_id for organism_id, done in flags if not done)
        reason = exclusions.get((unit_id, metric))
        organism_dates = sampling_dates[(unit_id, metric)]
        discordant_dates = len({tuple(dates) for dates in organism_dates.values()}) > 1
        expected_dates = sorted(schedule_by_unit.get(unit_id, ()))
        missing_scheduled = {
            organism_id: sorted(set(expected_dates) - set(dates))
            for organism_id, dates in sorted(organism_dates.items())
            if set(expected_dates) - set(dates)
        }
        if (unit_id, metric) in eligible and complete != len(flags):
            raise ValueError("Eligible experimental unit contains missing follow-up")
        if (unit_id, metric) in eligible and missing_scheduled:
            raise ValueError("Eligible unit cannot omit scheduled sampling visits")
        if (unit_id, metric) in eligible and unobserved_ids:
            raise ValueError("Eligible experimental unit omits expected organisms")
        if reason == "missing_expected_organisms" and not unobserved_ids:
            raise ValueError("Expected-roster exclusion requires unobserved organisms")
        if reason == "missing_followup" and complete == len(flags):
            raise ValueError("Missing-followup exclusion requires an incomplete organism")
        if reason == "missing_followup" and missing_scheduled:
            raise ValueError("Missing scheduled visits must take precedence over follow-up QC")
        if reason == "nonmatching_sampling_window" and complete != len(flags):
            raise ValueError("Sampling-window exclusion cannot conceal missing follow-up")
        if reason == "nonmatching_sampling_window" and unobserved_ids:
            raise ValueError("Sampling-window exclusion cannot conceal missing roster organisms")
        if reason == "nonmatching_sampling_window" and missing_scheduled:
            raise ValueError("Sampling-window exclusion cannot conceal missing scheduled visits")
        # A scheduled singleton is incomplete but still has actionable missing
        # calendar dates; retain both counts instead of rejecting its audit.
        if reason == "missing_scheduled_observations" and (not missing_scheduled or unobserved_ids):
            raise ValueError("Scheduled-visit exclusion must reflect missing scheduled dates")
        results.append(
            {
                "experimental_unit_id": unit_id,
                "metric_name": metric,
                "observed_organism_count": len(flags),
                "complete_organism_count": complete,
                "missing_followup_organism_count": len(missing_ids),
                "missing_organism_ids": missing_ids,
                "expected_organism_count": (
                    len(expected_by_unit[unit_id]) if unit_id in expected_by_unit else None
                ),
                "unobserved_organism_ids": unobserved_ids,
                "observed_sampling_dates_by_organism": dict(sorted(organism_dates.items())),
                "discordant_sampling_dates": discordant_dates,
                "expected_sampling_dates": expected_dates,
                "missing_scheduled_dates_by_organism": missing_scheduled,
                "eligible_for_summary": (unit_id, metric) in eligible,
                "exclusion_reason": reason,
            }
        )
    return results


def summarize_planned_sampling_effort(
    coverage: Iterable[Any],
) -> list[dict[str, Any]]:
    """Count scheduled organism-visits, not photographs or biological survival.

    When no expected organism roster exists, only *observed* organisms can
    contribute to the denominator. A declared roster additionally accounts
    for organisms never observed for the given metric. These are missing
    measurements, not evidence of death or a zero-valued observation.
    """
    summaries: list[dict[str, Any]] = []
    for row in sorted(coverage, key=lambda item: (item.experimental_unit_id, item.metric_name)):
        scheduled_dates = row.expected_sampling_dates
        if not scheduled_dates:
            continue
        organism_count = row.expected_organism_count or row.observed_organism_count
        expected_visits = organism_count * len(scheduled_dates)
        observed_visits = sum(
            len(dates) for dates in row.observed_sampling_dates_by_organism.values()
        )
        missing_visits = expected_visits - observed_visits
        audited_missing = sum(
            len(dates) for dates in row.missing_scheduled_dates_by_organism.values()
        ) + len(row.unobserved_organism_ids) * len(scheduled_dates)
        if missing_visits < 0 or missing_visits != audited_missing:
            raise ValueError("Planned sampling effort does not reconcile with unit coverage")
        summaries.append(
            {
                "experimental_unit_id": row.experimental_unit_id,
                "metric_name": row.metric_name,
                "planned_sampling_date_count": len(scheduled_dates),
                "expected_organism_count": organism_count,
                "expected_organism_visits": expected_visits,
                "observed_organism_visits": observed_visits,
                "missing_organism_visits": missing_visits,
                "observation_coverage_fraction": observed_visits / expected_visits,
                "expected_roster_supplied": row.expected_organism_count is not None,
            }
        )
    return summaries


def summarize_planned_sampling_dates(
    coverage: Iterable[Any],
) -> list[dict[str, Any]]:
    """Audit each planned UTC visit by biological organism, never by image.

    A roster adds completely unobserved organisms to every planned date.
    Missing measurements are not zero counts, absences or deaths.
    """
    results: list[dict[str, Any]] = []
    for row in sorted(coverage, key=lambda item: (item.experimental_unit_id, item.metric_name)):
        scheduled = row.expected_sampling_dates
        if not scheduled:
            continue
        observed = row.observed_sampling_dates_by_organism
        expected_ids = set(observed) | set(row.unobserved_organism_ids)
        count = row.expected_organism_count or row.observed_organism_count
        if len(expected_ids) != count:
            raise ValueError("Planned date roster disagrees with expected organism count")
        for day in scheduled:
            present = sorted(organism for organism, dates in observed.items() if day in dates)
            missing = sorted(expected_ids - set(present))
            results.append(
                {
                    "experimental_unit_id": row.experimental_unit_id,
                    "metric_name": row.metric_name,
                    "sampling_date": day,
                    "expected_organism_count": count,
                    "observed_organism_count": len(present),
                    "observed_organism_ids": present,
                    "missing_organism_ids": missing,
                    "observation_coverage_fraction": len(present) / count,
                    "expected_roster_supplied": row.expected_organism_count is not None,
                }
            )
    return results
