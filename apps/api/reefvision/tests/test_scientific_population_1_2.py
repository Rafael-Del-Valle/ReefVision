"""Scientific regression tests for unit-weighted, reproducible 1.2 summaries."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from reefvision.domain.errors import ValidationError
from reefvision.domain.population_unit_summaries import summarize_population_units
from reefvision.domain.scientific_mean import finite_descriptive_mean
from reefvision.schemas.longitudinal_monitoring import ExperimentalUnitSummary


def _unit(name: str, count: int, delta: float, *, days: int = 30):
    baseline = datetime(2026, 4, 3, 12, tzinfo=UTC)
    return ExperimentalUnitSummary(
        experimental_unit_id=name,
        metric_name="polyp_count",
        unit="count",
        organism_count=count,
        baseline_at=baseline,
        final_at=baseline + timedelta(days=days),
        mean_absolute_change=delta,
        mean_change_per_day=delta / days,
    )


def test_each_tank_has_one_vote_regardless_of_fragment_count() -> None:
    rows = [_unit("tank-B", 1, 10), _unit("tank-A", 12, 2)]
    summary = summarize_population_units(rows)[0]
    assert summary.independent_unit_count == 2
    assert summary.contributing_organism_count == 13
    assert summary.experimental_unit_ids == ["tank-A", "tank-B"]
    assert summary.mean_unit_absolute_change == 6
    assert summary.mean_unit_change_per_day == pytest.approx(0.2)


def test_mismatched_utc_sampling_windows_are_not_pooled() -> None:
    result = summarize_population_units([_unit("tank-A", 1, 1), _unit("tank-B", 1, 3, days=31)])
    assert len(result) == 2
    assert [row.independent_unit_count for row in result] == [1, 1]


def test_duplicate_unit_in_same_stratum_is_rejected() -> None:
    with pytest.raises(ValidationError, match="cannot contribute twice"):
        summarize_population_units([_unit("A", 1, 2), _unit("A", 1, 3)])


def test_cross_unit_mean_is_order_independent_and_overflow_safe() -> None:
    rows = [_unit("B", 1, 1e308), _unit("A", 4, 1e308)]
    forward = summarize_population_units(rows)
    backward = summarize_population_units(list(reversed(rows)))
    assert forward == backward
    assert forward[0].mean_unit_absolute_change == 1e308


def test_finite_mean_handles_large_values_and_cancellation() -> None:
    assert finite_descriptive_mean([1e308, 1e308]) == 1e308
    assert finite_descriptive_mean([1e308, -1e308, 1e308, -1e308]) == 0


def test_finite_mean_rejects_invalid_inputs() -> None:
    for values in ([], [math.nan], [math.inf], [1.0, -math.inf]):
        with pytest.raises(ValidationError):
            finite_descriptive_mean(values)


def test_descriptive_mean_order_is_deterministic() -> None:
    values = [1e15, 0.1, -1e15, 0.2, 0.3, 0.4]
    assert finite_descriptive_mean(values) == finite_descriptive_mean(reversed(values))


def test_summary_does_not_claim_verification_or_inference() -> None:
    payload = summarize_population_units([_unit("A", 5, 2)])[0].model_dump()
    for forbidden in ("verified", "p_value", "confidence_interval", "survival_rate"):
        assert forbidden not in payload
