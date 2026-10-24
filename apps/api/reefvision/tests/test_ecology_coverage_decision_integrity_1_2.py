"""Regression tests for experimental-unit coverage integrity."""

from datetime import UTC, datetime
from types import SimpleNamespace as Row

import pytest

from reefvision.domain.ecology_unit_coverage import audit_unit_coverage


def obs(unit: str) -> Row:
    return Row(experimental_unit_id=unit, observed_at=datetime(2026, 4, 1, tzinfo=UTC))


def change(name: str) -> Row:
    return Row(organism_id=name, metric_name="count")


def decision(unit: str) -> Row:
    return Row(experimental_unit_id=unit, metric_name="count")


def series() -> dict:
    return {
        ("a", "count"): [obs("tank"), obs("tank")],
        ("b", "count"): [obs("tank"), obs("tank")],
    }


def test_reject_duplicate_completed_organism() -> None:
    with pytest.raises(ValueError, match="Duplicate completed"):
        audit_unit_coverage(series(), [change("a"), change("a")], [], [])


def test_reject_incomplete_eligible_unit() -> None:
    with pytest.raises(ValueError, match="missing follow-up"):
        audit_unit_coverage(series(), [change("a")], [decision("tank")], [])


def test_reject_cross_metric_reassignment() -> None:
    data = {
        ("a", "count"): [obs("tank-1"), obs("tank-1")],
        ("a", "area"): [obs("tank-2"), obs("tank-2")],
    }
    with pytest.raises(ValueError, match="between metrics"):
        audit_unit_coverage(data, [], [], [])
