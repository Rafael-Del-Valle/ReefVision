"""Auditable denominators for longitudinal ecological experimental units.

Declared units remain unverified; this module reports descriptive coverage,
never independent experimental replication or statistical significance.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any


def audit_unit_coverage(
    grouped: Mapping[tuple[str, str], Sequence[Any]],
    changes: Iterable[Any],
    unit_summaries: Iterable[Any],
    excluded_units: Iterable[Any],
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
        by_unit_metric[(unit_id, metric_name)].append(
            (organism_id, (organism_id, metric_name) in completed)
        )

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
    for (unit_id, metric), flags in sorted(by_unit_metric.items()):
        complete = sum(is_complete for _, is_complete in flags)
        missing_ids = sorted(organism_id for organism_id, done in flags if not done)
        reason = exclusions.get((unit_id, metric))
        if (unit_id, metric) in eligible and complete != len(flags):
            raise ValueError("Eligible experimental unit contains missing follow-up")
        if reason == "missing_followup" and complete == len(flags):
            raise ValueError("Missing-followup exclusion requires an incomplete organism")
        if reason == "nonmatching_sampling_window" and complete != len(flags):
            raise ValueError("Sampling-window exclusion cannot conceal missing follow-up")
        results.append(
            {
                "experimental_unit_id": unit_id,
                "metric_name": metric,
                "observed_organism_count": len(flags),
                "complete_organism_count": complete,
                "missing_followup_organism_count": len(missing_ids),
                "missing_organism_ids": missing_ids,
                "eligible_for_summary": (unit_id, metric) in eligible,
                "exclusion_reason": reason,
            }
        )
    return results
