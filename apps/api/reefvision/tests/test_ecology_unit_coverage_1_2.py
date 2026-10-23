"""Focused invariants for experimental-unit follow-up coverage auditing."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from reefvision.domain.ecology_unit_coverage import audit_unit_coverage


def _observation(unit_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        experimental_unit_id=unit_id, observed_at=datetime(2026, 4, 1, tzinfo=UTC)
    )


def _change(organism_id: str, metric: str = "polyp_count") -> SimpleNamespace:
    return SimpleNamespace(organism_id=organism_id, metric_name=metric)


def _unit(unit_id: str, metric: str = "polyp_count") -> SimpleNamespace:
    return SimpleNamespace(experimental_unit_id=unit_id, metric_name=metric)


def _excluded(unit_id: str, reason: str, metric: str = "polyp_count") -> SimpleNamespace:
    return SimpleNamespace(experimental_unit_id=unit_id, metric_name=metric, reason=reason)


def test_excluded_tank_reports_missing_followup_without_pseudoreplication() -> None:
    grouped = {
        ("frag-1", "polyp_count"): [_observation("tank-1"), _observation("tank-1")],
        ("frag-2", "polyp_count"): [_observation("tank-1")],
        ("frag-3", "polyp_count"): [_observation("tank-2"), _observation("tank-2")],
    }
    result = audit_unit_coverage(
        grouped,
        [_change("frag-1"), _change("frag-3")],
        [_unit("tank-2")],
        [_excluded("tank-1", "missing_followup")],
    )
    assert result[0]["experimental_unit_id"] == "tank-1"
    assert result[0]["observed_organism_count"] == 2
    assert result[0]["complete_organism_count"] == 1
    assert result[0]["missing_followup_organism_count"] == 1
    assert result[0]["eligible_for_summary"] is False
    assert result[1]["eligible_for_summary"] is True


def test_nonmatching_window_cannot_hide_missing_followup() -> None:
    grouped = {
        ("a", "area"): [_observation("tank-1"), _observation("tank-1")],
        ("b", "area"): [_observation("tank-1")],
    }
    with pytest.raises(ValueError, match="cannot conceal"):
        audit_unit_coverage(
            grouped,
            [_change("a", "area")],
            [],
            [_excluded("tank-1", "nonmatching_sampling_window", "area")],
        )


def test_missing_unit_decision_fails_closed() -> None:
    grouped = {("a", "count"): [_observation("tank-1"), _observation("tank-1")]}
    with pytest.raises(ValueError, match="does not reconcile"):
        audit_unit_coverage(grouped, [_change("a", "count")], [], [])


def test_coverage_sorted_independently_of_input_order() -> None:
    grouped = {
        ("z", "count"): [_observation("tank-B"), _observation("tank-B")],
        ("a", "count"): [_observation("tank-A"), _observation("tank-A")],
    }
    result = audit_unit_coverage(
        grouped,
        [_change("z", "count"), _change("a", "count")],
        [_unit("tank-B", "count"), _unit("tank-A", "count")],
        [],
    )
    assert [row["experimental_unit_id"] for row in result] == ["tank-A", "tank-B"]
