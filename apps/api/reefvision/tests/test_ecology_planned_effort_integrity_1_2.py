"""Scientific denominator integrity for unverified planned organism-visits."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from reefvision.domain.ecology_unit_coverage import summarize_planned_sampling_effort


def _coverage() -> SimpleNamespace:
    days = [date(2026, 4, day) for day in (1, 2, 3)]
    return SimpleNamespace(
        experimental_unit_id="tank-1",
        metric_name="polyp_count",
        expected_sampling_dates=days,
        expected_organism_count=3,
        observed_organism_count=2,
        observed_sampling_dates_by_organism={
            "A": days,
            "B": [days[0], days[2]],
        },
        missing_scheduled_dates_by_organism={"B": [days[1]]},
        unobserved_organism_ids=["C"],
    )


def test_expected_roster_missing_visits_reconcile_without_zero_abundance() -> None:
    result = summarize_planned_sampling_effort([_coverage()])
    assert len(result) == 1
    assert result[0]["expected_organism_visits"] == 9
    assert result[0]["observed_organism_visits"] == 5
    assert result[0]["missing_organism_visits"] == 4
    assert result[0]["observation_coverage_fraction"] == pytest.approx(5 / 9)
    assert result[0]["expected_roster_supplied"] is True


def test_forged_missing_visit_audit_cannot_produce_scientific_effort() -> None:
    coverage = _coverage()
    coverage.missing_scheduled_dates_by_organism = {}
    with pytest.raises(ValueError, match="does not reconcile"):
        summarize_planned_sampling_effort([coverage])


def test_no_planned_calendar_cannot_invent_effort_denominator() -> None:
    coverage = _coverage()
    coverage.expected_sampling_dates = []
    assert summarize_planned_sampling_effort([coverage]) == []
