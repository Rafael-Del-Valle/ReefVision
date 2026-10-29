"""Domain scientific checks for paired human-model comparisons."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as SchemaValidationError

from reefvision.domain.errors import ValidationError
from reefvision.domain.model_agreement import compare_paired_counts
from reefvision.schemas.model_agreement import PairedCountComparisonRequest


def pair(
    identifier: str, organism: str, unit: str, human: float, model: float
) -> dict[str, object]:
    return {
        "observation_id": identifier,
        "organism_id": organism,
        "metric_name": "polyp_count",
        "reference_source_record_id": f"human-{identifier}",
        "model_source_record_id": f"model-{identifier}",
        "reference_count": human,
        "model_count": model,
        "experimental_unit_id": unit,
        "experimental_unit_type": "tank",
    }


def test_paired_bias_mae_and_independent_tank_denominator() -> None:
    request = PairedCountComparisonRequest(
        reference_kind="human_consensus",
        pairs=[
            pair("image-1", "fragment-A", "tank-1", 10, 12),
            pair("image-2", "fragment-B", "tank-1", 20, 16),
            pair("image-3", "fragment-C", "tank-2", 5, 8),
        ],
    )
    result = compare_paired_counts(request)
    assert result.evidence_level == "caller_supplied_unverified"
    assert result.review_status == "requires_source_verification"
    assert result.paired_observation_count == 3
    assert result.mean_signed_bias == pytest.approx(1 / 3)
    assert result.mean_absolute_error == pytest.approx(3)
    assert result.mean_absolute_percent_deviation == pytest.approx((20 + 20 + 60) / 3)
    assert result.declared_independent_unit_count == 2
    assert result.unit_summaries[0].organism_count == 2
    assert result.unit_summaries[0].mean_signed_bias == pytest.approx(-1)


def test_zero_reference_excluded_from_percent_not_absolute_error() -> None:
    request = PairedCountComparisonRequest(
        reference_kind="human_observer",
        pairs=[
            pair("a", "frag-a", "tank-1", 0, 3),
            pair("b", "frag-b", "tank-2", 10, 12),
        ],
    )
    result = compare_paired_counts(request)
    assert result.zero_reference_count == 1
    assert result.nonzero_reference_count == 1
    assert result.mean_absolute_percent_deviation == pytest.approx(20)
    assert result.mean_absolute_error == pytest.approx(2.5)
    assert result.paired_differences[0].absolute_percent_deviation is None


def test_duplicate_sources_and_cross_unit_organism_rejected() -> None:
    data = [
        pair("a", "same-frag", "tank-1", 10, 11),
        pair("b", "same-frag", "tank-2", 10, 12),
    ]
    with pytest.raises(ValidationError, match="change experimental units"):
        compare_paired_counts(
            PairedCountComparisonRequest(reference_kind="human_consensus", pairs=data)
        )
    data[1]["organism_id"] = "different-frag"
    data[1]["reference_source_record_id"] = data[0]["reference_source_record_id"]
    with pytest.raises(ValidationError, match="source record IDs"):
        compare_paired_counts(
            PairedCountComparisonRequest(reference_kind="human_consensus", pairs=data)
        )


def test_undeclared_unit_and_mixed_metrics_rejected() -> None:
    data = [
        pair("a", "frag-a", "tank-1", 10, 11),
        pair("b", "frag-b", "tank-2", 10, 12),
    ]
    for row in data:
        row.pop("experimental_unit_type")
    with pytest.raises(ValidationError, match="experimental_unit_type"):
        compare_paired_counts(
            PairedCountComparisonRequest(reference_kind="human_observer", pairs=data)
        )
    for row in data:
        row["experimental_unit_type"] = "tank"
    data[1]["metric_name"] = "open_polyp_count"
    with pytest.raises(ValidationError, match="mixed metrics"):
        compare_paired_counts(
            PairedCountComparisonRequest(reference_kind="human_observer", pairs=data)
        )


def test_forged_verification_and_nonfinite_counts_rejected() -> None:
    data = [
        pair("a", "frag-a", "tank-1", 10, 11),
        pair("b", "frag-b", "tank-2", 10, 12),
    ]
    data[0]["verified"] = True
    with pytest.raises(SchemaValidationError, match="Extra inputs"):
        PairedCountComparisonRequest(reference_kind="human_consensus", pairs=data)
    data[0].pop("verified")
    data[0]["model_count"] = float("inf")
    with pytest.raises(SchemaValidationError, match="finite"):
        PairedCountComparisonRequest(reference_kind="human_consensus", pairs=data)


def test_finite_large_bias_and_unit_means_do_not_overflow() -> None:
    rows = [
        pair("large-a", "frag-a", "tank-1", 0, 1e308),
        pair("large-b", "frag-b", "tank-1", 0, 1e308),
    ]
    result = compare_paired_counts(
        PairedCountComparisonRequest(reference_kind="human_consensus", pairs=rows)
    )
    assert result.mean_signed_bias == 1e308
    assert result.mean_absolute_error == 1e308
    assert result.unit_summaries[0].mean_signed_bias == 1e308
    assert result.zero_reference_count == 2
    assert result.mean_absolute_percent_deviation is None
    assert result.evidence_level == "caller_supplied_unverified"


def test_pair_frequency_audit_exposes_nested_pseudoreplication_risk() -> None:
    """Four images are three organisms and only two caller-declared tanks."""
    rows = [
        pair("a1", "fragment-A", "tank-1", 10, 12),
        pair("a2", "fragment-A", "tank-1", 10, 13),
        pair("b", "fragment-B", "tank-1", 10, 11),
        pair("c", "fragment-C", "tank-2", 10, 8),
    ]
    result = compare_paired_counts(
        PairedCountComparisonRequest(reference_kind="human_consensus", pairs=rows)
    )
    assert result.paired_observation_count == 4
    assert result.observed_organism_count == 3
    assert result.declared_independent_unit_count == 2
    assert result.observation_counts_by_organism == {
        "fragment-A": 2,
        "fragment-B": 1,
        "fragment-C": 1,
    }
    assert result.repeated_pair_count_beyond_first_per_organism == 1
    assert result.unequal_pair_counts_across_organisms is True
    first, second = result.unit_summaries
    assert first.experimental_unit_id == "tank-1"
    assert first.observation_counts_by_organism == {"fragment-A": 2, "fragment-B": 1}
    assert first.repeated_pair_count_beyond_first_per_organism == 1
    assert first.unequal_pair_counts_within_unit is True
    assert second.repeated_pair_count_beyond_first_per_organism == 0
    assert second.unequal_pair_counts_within_unit is False
    assert result.mean_signed_bias == pytest.approx(1)
    assert result.organism_and_unit_balanced_mean_signed_bias == pytest.approx(-0.125)
    assert result.evidence_level == "caller_supplied_unverified"
    assert result.review_status == "requires_source_verification"
    assert result.analysis_provenance.algorithm_version == "ecology-paired-count-0004"


def test_equal_pair_frequencies_do_not_raise_false_imbalance() -> None:
    rows = [
        pair("a1", "fragment-A", "tank-1", 10, 11),
        pair("a2", "fragment-A", "tank-1", 10, 12),
        pair("b1", "fragment-B", "tank-1", 10, 11),
        pair("b2", "fragment-B", "tank-1", 10, 12),
    ]
    result = compare_paired_counts(
        PairedCountComparisonRequest(reference_kind="human_observer", pairs=rows)
    )
    assert result.observed_organism_count == 2
    assert result.repeated_pair_count_beyond_first_per_organism == 2
    assert result.unequal_pair_counts_across_organisms is False
    assert result.unit_summaries[0].unequal_pair_counts_within_unit is False
