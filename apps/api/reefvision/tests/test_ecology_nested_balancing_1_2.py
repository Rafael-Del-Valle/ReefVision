"""Nested organism/unit balancing and zero-reference denominators."""

from __future__ import annotations

import pytest

from reefvision.domain.errors import ValidationError
from reefvision.domain.model_agreement import compare_paired_counts
from reefvision.schemas.model_agreement import PairedCountComparisonRequest


def pair(key: str, organism: str, unit: str, reference: int, model: int) -> dict:
    return {
        "observation_id": key,
        "organism_id": organism,
        "metric_name": "polyp_count",
        "reference_source_record_id": f"human-{key}",
        "model_source_record_id": f"model-{key}",
        "reference_count": reference,
        "model_count": model,
        "experimental_unit_id": unit,
        "experimental_unit_type": "tank",
    }


def compare(pairs: list[dict]):
    return compare_paired_counts(
        PairedCountComparisonRequest(reference_kind="human_consensus", pairs=pairs)
    )


def test_nested_balancing_reduces_technical_replication_weight() -> None:
    pairs = [
        pair("a1", "A", "tank-1", 10, 20),
        pair("a2", "A", "tank-1", 10, 20),
        pair("a3", "A", "tank-1", 10, 20),
        pair("b1", "B", "tank-1", 10, 10),
        pair("c1", "C", "tank-2", 10, 12),
    ]
    result = compare(pairs)
    assert result.mean_absolute_percent_deviation == pytest.approx(64)
    assert result.unit_balanced_mean_absolute_percent_deviation == pytest.approx(47.5)
    assert result.organism_and_unit_balanced_mean_absolute_percent_deviation == pytest.approx(35)
    assert result.percent_contributing_independent_unit_count == 2
    assert result.percent_contributing_organism_count == 3
    assert result.evidence_level == "caller_supplied_unverified"
    assert compare(list(reversed(pairs))).model_dump() == result.model_dump()


def test_zero_reference_excludes_only_ineligible_percentages() -> None:
    result = compare(
        [
            pair("a0", "A", "tank-1", 0, 10),
            pair("a1", "A", "tank-1", 10, 20),
            pair("b0", "B", "tank-1", 0, 10),
            pair("c0", "C", "tank-2", 0, 10),
        ]
    )
    assert result.zero_reference_count == 3
    assert result.percent_contributing_independent_unit_count == 1
    assert result.percent_contributing_organism_count == 1
    assert result.organism_and_unit_balanced_mean_absolute_percent_deviation == 100
    assert result.unit_summaries[1].mean_absolute_percent_deviation is None


def test_all_zero_reference_percentages_are_null() -> None:
    result = compare(
        [
            pair("a", "A", "tank-1", 0, 10),
            pair("b", "B", "tank-2", 0, 10),
        ]
    )
    assert result.mean_absolute_percent_deviation is None
    assert result.unit_balanced_mean_absolute_percent_deviation is None
    assert result.organism_and_unit_balanced_mean_absolute_percent_deviation is None
    assert result.percent_contributing_independent_unit_count == 0
    assert result.percent_contributing_organism_count == 0


def test_human_model_source_id_collision_is_rejected() -> None:
    pairs = [
        pair("a", "A", "tank-1", 10, 12),
        pair("b", "B", "tank-1", 10, 12),
    ]
    pairs[1]["model_source_record_id"] = pairs[0]["reference_source_record_id"]
    with pytest.raises(ValidationError, match="must be distinct"):
        compare(pairs)
