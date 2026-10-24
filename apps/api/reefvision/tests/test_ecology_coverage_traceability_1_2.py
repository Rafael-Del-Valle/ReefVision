"""Scientific regression checks for traceable 1.2 experimental-unit coverage."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace as Row

import pytest

from reefvision.domain.ecology_unit_coverage import audit_unit_coverage
from reefvision.schemas.longitudinal_monitoring import ExperimentalUnitCoverage


def observation(unit: str) -> Row:
    return Row(experimental_unit_id=unit, observed_at=datetime(2026, 4, 1, tzinfo=UTC))


def change(organism: str) -> Row:
    return Row(organism_id=organism, metric_name="polyp_count")


def decision(unit: str, count: int | None = None) -> Row:
    return Row(
        experimental_unit_id=unit,
        metric_name="polyp_count",
        organism_count=count,
    )


def excluded(unit: str) -> Row:
    return Row(
        experimental_unit_id=unit,
        metric_name="polyp_count",
        reason="missing_followup",
    )


def grouped() -> dict[tuple[str, str], list[Row]]:
    return {
        ("fragment-z", "polyp_count"): [observation("tank-1")],
        ("fragment-a", "polyp_count"): [observation("tank-1")],
        ("fragment-c", "polyp_count"): [
            observation("tank-1"),
            observation("tank-1"),
        ],
    }


def test_missing_organisms_are_sorted_and_excluded_from_replication() -> None:
    rows = audit_unit_coverage(grouped(), [change("fragment-c")], [], [excluded("tank-1")])
    assert len(rows) == 1
    coverage = ExperimentalUnitCoverage.model_validate(rows[0])
    assert coverage.missing_organism_ids == ["fragment-a", "fragment-z"]
    assert coverage.observed_organism_count == 3
    assert coverage.complete_organism_count == 1
    assert coverage.missing_followup_organism_count == 2
    assert coverage.eligible_for_summary is False
    assert coverage.exclusion_reason == "missing_followup"
    reversed_rows = audit_unit_coverage(
        dict(reversed(list(grouped().items()))),
        [change("fragment-c")],
        [],
        [excluded("tank-1")],
    )
    assert rows == reversed_rows


def test_duplicate_eligible_and_excluded_unit_decisions_are_rejected() -> None:
    data = {
        ("a", "polyp_count"): [
            observation("tank-1"),
            observation("tank-1"),
        ]
    }
    with pytest.raises(ValueError, match="Duplicate eligible"):
        audit_unit_coverage(data, [change("a")], [decision("tank-1"), decision("tank-1")], [])
    with pytest.raises(ValueError, match="Duplicate excluded"):
        audit_unit_coverage(data, [], [], [excluded("tank-1"), excluded("tank-1")])


def test_forged_single_observation_completion_is_rejected() -> None:
    data = {("a", "polyp_count"): [observation("tank-1")]}
    with pytest.raises(ValueError, match="requires repeated observations"):
        audit_unit_coverage(data, [change("a")], [decision("tank-1")], [])


def test_inflated_unit_organism_denominator_is_rejected() -> None:
    data = {
        ("a", "polyp_count"): [
            observation("tank-1"),
            observation("tank-1"),
        ]
    }
    with pytest.raises(ValueError, match="count disagrees with coverage"):
        audit_unit_coverage(data, [change("a")], [decision("tank-1", 3)], [])


def test_legacy_coverage_payload_remains_parseable() -> None:
    legacy = {
        "experimental_unit_id": "tank-1",
        "metric_name": "polyp_count",
        "observed_organism_count": 1,
        "complete_organism_count": 1,
        "missing_followup_organism_count": 0,
        "eligible_for_summary": True,
    }
    assert ExperimentalUnitCoverage.model_validate(legacy).missing_organism_ids == []
