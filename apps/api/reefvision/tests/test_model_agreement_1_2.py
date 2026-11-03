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
    assert result.mean_signed_percent_deviation == pytest.approx((20 - 20 + 60) / 3)
    assert result.unit_balanced_mean_signed_percent_deviation == pytest.approx(30)
    assert result.organism_and_unit_balanced_mean_signed_percent_deviation == pytest.approx(30)
    assert [row.signed_percent_deviation for row in result.paired_differences] == [20, -20, 60]
    assert result.declared_independent_unit_count == 2
    assert result.overcount_pair_count == 2
    assert result.undercount_pair_count == 1
    assert result.exact_match_pair_count == 0
    assert result.unit_summaries[0].overcount_pair_count == 1
    assert result.unit_summaries[0].undercount_pair_count == 1
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
    assert result.overcount_pair_count == 2
    assert result.undercount_pair_count == 0
    assert result.exact_match_pair_count == 0
    assert result.paired_differences[0].absolute_percent_deviation is None
    assert result.paired_differences[0].signed_percent_deviation is None
    assert result.mean_signed_percent_deviation == pytest.approx(20)
    assert result.percent_contributing_independent_unit_count == 1


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
    with pytest.raises(SchemaValidationError, match="safe-integer range"):
        PairedCountComparisonRequest(reference_kind="human_consensus", pairs=data)


def test_max_safe_integer_bias_and_unit_means_are_exact() -> None:
    """Large *valid* counts remain stable without exceeding JSON precision."""
    max_count = float(2**53 - 1)
    rows = [
        pair("large-a", "frag-a", "tank-1", 0, max_count),
        pair("large-b", "frag-b", "tank-1", 0, max_count),
    ]
    result = compare_paired_counts(
        PairedCountComparisonRequest(reference_kind="human_consensus", pairs=rows)
    )
    assert result.mean_signed_bias == max_count
    assert result.mean_absolute_error == max_count
    assert result.unit_summaries[0].mean_signed_bias == max_count
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
    assert result.mean_signed_percent_deviation == pytest.approx(10)
    assert result.unit_balanced_mean_signed_percent_deviation == pytest.approx(0)
    assert result.organism_and_unit_balanced_mean_signed_percent_deviation == pytest.approx(-1.25)
    assert result.evidence_level == "caller_supplied_unverified"
    assert result.review_status == "requires_source_verification"
    assert result.analysis_provenance.algorithm_version == "ecology-paired-count-0007"


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


def test_directional_pair_frequencies_include_zero_reference_and_exact_matches() -> None:
    """Directional counts describe image pairs, not independent organisms."""
    rows = [
        pair("zero-human", "frag-a", "tank-1", 0, 3),
        pair("exact", "frag-a", "tank-1", 8, 8),
        pair("under", "frag-b", "tank-2", 12, 9),
        pair("over", "frag-b", "tank-2", 10, 11),
    ]
    result = compare_paired_counts(
        PairedCountComparisonRequest(reference_kind="human_consensus", pairs=rows)
    )
    assert result.paired_observation_count == 4
    assert result.observed_organism_count == 2
    assert result.declared_independent_unit_count == 2
    assert result.zero_reference_count == 1
    assert result.overcount_pair_count == 2
    assert result.undercount_pair_count == 1
    assert result.exact_match_pair_count == 1
    assert [
        (unit.overcount_pair_count, unit.undercount_pair_count, unit.exact_match_pair_count)
        for unit in result.unit_summaries
    ] == [(1, 0, 1), (1, 1, 0)]
    assert result.analysis_provenance.algorithm_version == "ecology-paired-count-0007"
    assert result.review_status == "requires_source_verification"
    assert result.evidence_level == "caller_supplied_unverified"


def test_organism_direction_votes_do_not_treat_repeated_images_as_replicates() -> None:
    """Opposing image errors can balance for one organism without exact images."""
    rows = [
        pair("a1", "frag-A", "tank-1", 10, 13),
        pair("a2", "frag-A", "tank-1", 10, 7),
        pair("b", "frag-B", "tank-1", 10, 12),
        pair("c", "frag-C", "tank-2", 10, 9),
    ]
    result = compare_paired_counts(
        PairedCountComparisonRequest(reference_kind="human_observer", pairs=rows)
    )
    assert result.paired_observation_count == 4
    assert result.observed_organism_count == 3
    assert (result.overcount_pair_count, result.undercount_pair_count) == (2, 2)
    assert result.exact_match_pair_count == 0
    assert (
        result.overcount_organism_count,
        result.undercount_organism_count,
        result.balanced_organism_count,
    ) == (1, 1, 1)
    assert [
        (
            unit.overcount_organism_count,
            unit.undercount_organism_count,
            unit.balanced_organism_count,
        )
        for unit in result.unit_summaries
    ] == [(1, 0, 1), (0, 1, 0)]
    assert result.analysis_provenance.algorithm_version == "ecology-paired-count-0007"
    assert result.review_status == "requires_source_verification"


def test_organism_direction_fields_remain_optional_for_old_saved_artifacts() -> None:
    """Earlier typed artifacts decode without inventing historical vote evidence."""
    from reefvision.schemas.model_agreement import PairedCountComparisonResponse

    result = compare_paired_counts(
        PairedCountComparisonRequest(
            reference_kind="human_consensus",
            pairs=[
                pair("a", "frag-A", "tank-1", 10, 11),
                pair("b", "frag-B", "tank-2", 10, 9),
            ],
        )
    )
    old = result.model_dump(mode="json")
    old["analysis_provenance"]["algorithm_version"] = "ecology-paired-count-0006"
    for key in (
        "overcount_organism_count",
        "undercount_organism_count",
        "balanced_organism_count",
    ):
        old.pop(key)
        for unit in old["unit_summaries"]:
            unit.pop(key)
    restored = PairedCountComparisonResponse.model_validate(old)
    assert restored.overcount_organism_count == 0
    assert restored.undercount_organism_count == 0
    assert restored.balanced_organism_count == 0
    assert restored.unit_summaries[0].overcount_organism_count == 0


@pytest.mark.parametrize(
    ("scope", "field"),
    [
        ("global", "overcount_pair_count"),
        ("global", "balanced_organism_count"),
        ("unit", "undercount_pair_count"),
        ("unit", "overcount_organism_count"),
    ],
)
def test_current_directional_artifact_rejects_forged_denominators(scope: str, field: str) -> None:
    """A saved 0007 artifact cannot silently inflate image or organism sample size."""
    from reefvision.schemas.model_agreement import PairedCountComparisonResponse

    result = compare_paired_counts(
        PairedCountComparisonRequest(
            reference_kind="human_consensus",
            pairs=[
                pair("a", "frag-A", "tank-1", 10, 12),
                pair("b", "frag-B", "tank-2", 10, 8),
            ],
        )
    )
    payload = result.model_dump(mode="json")
    target = payload if scope == "global" else payload["unit_summaries"][0]
    target[field] += 1
    with pytest.raises(SchemaValidationError, match="Directional"):
        PairedCountComparisonResponse.model_validate(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        "swapped_direction_labels",
        "forged_organism_frequency",
        "forged_reference_denominator",
        "missing_paired_row",
    ],
)
def test_current_saved_directional_artifact_rejects_plausible_but_false_totals(
    mutation: str,
) -> None:
    """A numerically plausible persisted summary cannot contradict its paired rows."""
    from reefvision.schemas.model_agreement import PairedCountComparisonResponse

    result = compare_paired_counts(
        PairedCountComparisonRequest(
            reference_kind="human_consensus",
            pairs=[
                pair("a", "frag-A", "tank-1", 10, 12),
                pair("b", "frag-B", "tank-2", 10, 8),
            ],
        )
    )
    payload = result.model_dump(mode="json")
    if mutation == "swapped_direction_labels":
        # Still sums to two, but contradicts the signed paired differences.
        payload["overcount_pair_count"] = 0
        payload["undercount_pair_count"] = 2
    elif mutation == "forged_organism_frequency":
        payload["observation_counts_by_organism"] = {"frag-A": 2}
    elif mutation == "forged_reference_denominator":
        payload["nonzero_reference_count"] = 1
    else:
        payload["paired_differences"].pop()
    with pytest.raises(SchemaValidationError, match="Directional"):
        PairedCountComparisonResponse.model_validate(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        "signed_difference",
        "absolute_difference",
        "signed_percent",
        "absolute_percent",
        "zero_reference_percent",
        "negative_model",
    ],
)
def test_current_saved_paired_rows_reject_forged_arithmetic(mutation: str) -> None:
    """A plausible direction tally cannot conceal altered model/reference arithmetic."""
    from reefvision.schemas.model_agreement import PairedCountComparisonResponse

    result = compare_paired_counts(
        PairedCountComparisonRequest(
            reference_kind="human_consensus",
            pairs=[
                pair("a", "frag-A", "tank-1", 10, 12),
                pair("b", "frag-B", "tank-2", 0, 8),
            ],
        )
    )
    payload = result.model_dump(mode="json")
    first, second = payload["paired_differences"]
    if mutation == "signed_difference":
        first["signed_difference"] = -2
    elif mutation == "absolute_difference":
        first["absolute_difference"] = 1
    elif mutation == "signed_percent":
        first["signed_percent_deviation"] = -20
    elif mutation == "absolute_percent":
        first["absolute_percent_deviation"] = 40
    elif mutation == "zero_reference_percent":
        second["absolute_percent_deviation"] = 0
    else:
        first["model_count"] = -1
    with pytest.raises(SchemaValidationError, match="Directional"):
        PairedCountComparisonResponse.model_validate(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_unit_id",
        "duplicate_organism",
        "forged_unit_frequency",
        "forged_repeat",
        "forged_imbalance",
        "forged_percent_units",
        "forged_percent_organisms",
        "missing_unit_summaries",
    ],
)
def test_current_saved_unit_roster_rejects_pseudoreplicate_tampering(
    mutation: str,
) -> None:
    """Two caller-declared tanks cannot silently become duplicate biological units."""
    from reefvision.schemas.model_agreement import PairedCountComparisonResponse

    result = compare_paired_counts(
        PairedCountComparisonRequest(
            reference_kind="human_consensus",
            pairs=[
                pair("a", "frag-A", "tank-1", 10, 12),
                pair("b", "frag-B", "tank-2", 10, 8),
            ],
        )
    )
    payload = result.model_dump(mode="json")
    first, second = payload["unit_summaries"]
    if mutation == "duplicate_unit_id":
        second["experimental_unit_id"] = first["experimental_unit_id"]
    elif mutation == "duplicate_organism":
        second["observation_counts_by_organism"] = {"frag-A": 1}
    elif mutation == "forged_unit_frequency":
        first["observation_counts_by_organism"] = {"frag-A": 2}
    elif mutation == "forged_repeat":
        first["repeated_pair_count_beyond_first_per_organism"] = 1
    elif mutation == "forged_imbalance":
        first["unequal_pair_counts_within_unit"] = True
    elif mutation == "forged_percent_units":
        payload["percent_contributing_independent_unit_count"] = 1
    elif mutation == "forged_percent_organisms":
        payload["percent_contributing_organism_count"] = 1
    else:
        payload["unit_summaries"] = []
    with pytest.raises(SchemaValidationError, match="Directional"):
        PairedCountComparisonResponse.model_validate(payload)


@pytest.mark.parametrize(
    "field",
    [
        "mean_signed_bias",
        "mean_absolute_error",
        "mean_absolute_percent_deviation",
        "mean_signed_percent_deviation",
        "unit_balanced_mean_signed_bias",
        "unit_balanced_mean_absolute_error",
        "organism_and_unit_balanced_mean_signed_bias",
        "organism_and_unit_balanced_mean_absolute_error",
        "unit_balanced_mean_absolute_percent_deviation",
        "organism_and_unit_balanced_mean_absolute_percent_deviation",
        "unit_balanced_mean_signed_percent_deviation",
        "organism_and_unit_balanced_mean_signed_percent_deviation",
    ],
)
def test_current_saved_paired_means_reject_forged_aggregates(field: str) -> None:
    """Saved 0007 means must reconcile with rows and unit summaries."""
    from reefvision.schemas.model_agreement import PairedCountComparisonResponse

    result = compare_paired_counts(
        PairedCountComparisonRequest(
            reference_kind="human_consensus",
            pairs=[
                pair("a", "frag-A", "tank-1", 10, 12),
                pair("b", "frag-B", "tank-2", 20, 16),
            ],
        )
    )
    payload = result.model_dump(mode="json")
    payload[field] += 5
    with pytest.raises(SchemaValidationError, match="Directional"):
        PairedCountComparisonResponse.model_validate(payload)


def test_current_saved_zero_reference_means_cannot_be_forged() -> None:
    """No nonzero reference means no percentage estimate, not zero error."""
    from reefvision.schemas.model_agreement import PairedCountComparisonResponse

    result = compare_paired_counts(
        PairedCountComparisonRequest(
            reference_kind="human_observer",
            pairs=[
                pair("a", "frag-A", "tank-1", 0, 3),
                pair("b", "frag-B", "tank-2", 0, 5),
            ],
        )
    )
    payload = result.model_dump(mode="json")
    assert payload["mean_absolute_percent_deviation"] is None
    payload["mean_absolute_percent_deviation"] = 0
    with pytest.raises(SchemaValidationError, match="Directional"):
        PairedCountComparisonResponse.model_validate(payload)


def test_current_saved_nonzero_reference_requires_signed_percentage() -> None:
    """Current artifacts cannot omit signed percent while retaining absolute percent."""
    from reefvision.schemas.model_agreement import PairedCountComparisonResponse

    result = compare_paired_counts(
        PairedCountComparisonRequest(
            reference_kind="human_consensus",
            pairs=[
                pair("a", "frag-A", "tank-1", 10, 12),
                pair("b", "frag-B", "tank-2", 10, 8),
            ],
        )
    )
    payload = result.model_dump(mode="json")
    payload["paired_differences"][0]["signed_percent_deviation"] = None
    with pytest.raises(SchemaValidationError, match="Directional"):
        PairedCountComparisonResponse.model_validate(payload)


@pytest.mark.parametrize(
    ("unit_field", "aggregate_field"),
    [
        ("mean_signed_bias", "unit_balanced_mean_signed_bias"),
        ("mean_absolute_error", "unit_balanced_mean_absolute_error"),
        (
            "organism_balanced_mean_signed_bias",
            "organism_and_unit_balanced_mean_signed_bias",
        ),
        (
            "organism_balanced_mean_absolute_error",
            "organism_and_unit_balanced_mean_absolute_error",
        ),
        (
            "mean_absolute_percent_deviation",
            "unit_balanced_mean_absolute_percent_deviation",
        ),
        (
            "organism_balanced_mean_absolute_percent_deviation",
            "organism_and_unit_balanced_mean_absolute_percent_deviation",
        ),
        (
            "mean_signed_percent_deviation",
            "unit_balanced_mean_signed_percent_deviation",
        ),
        (
            "organism_balanced_mean_signed_percent_deviation",
            "organism_and_unit_balanced_mean_signed_percent_deviation",
        ),
    ],
)
def test_saved_unit_mean_cannot_be_forged_with_matching_aggregate(
    unit_field: str, aggregate_field: str
) -> None:
    """Changing a tank mean and the corresponding grand mean must fail closed."""
    from reefvision.schemas.model_agreement import PairedCountComparisonResponse

    result = compare_paired_counts(
        PairedCountComparisonRequest(
            reference_kind="human_consensus",
            pairs=[
                pair("a", "frag-A", "tank-1", 10, 12),
                pair("b", "frag-B", "tank-1", 20, 16),
            ],
        )
    )
    payload = result.model_dump(mode="json")
    payload["unit_summaries"][0][unit_field] += 1
    payload[aggregate_field] += 1
    with pytest.raises(SchemaValidationError, match="Directional"):
        PairedCountComparisonResponse.model_validate(payload)


@pytest.mark.parametrize("vote_kind", ["pair", "organism"])
def test_saved_tank_direction_swap_rejected_despite_unchanged_global_totals(
    vote_kind: str,
) -> None:
    """Opposite-sign tanks cannot exchange directional votes in persisted results."""
    from reefvision.schemas.model_agreement import PairedCountComparisonResponse

    result = compare_paired_counts(
        PairedCountComparisonRequest(
            reference_kind="human_consensus",
            pairs=[
                pair("a", "frag-A", "tank-1", 10, 12),
                pair("b", "frag-B", "tank-2", 10, 8),
            ],
        )
    )
    payload = result.model_dump(mode="json")
    over = f"overcount_{vote_kind}_count"
    under = f"undercount_{vote_kind}_count"
    for unit in payload["unit_summaries"]:
        unit[over], unit[under] = unit[under], unit[over]
    assert sum(unit[over] for unit in payload["unit_summaries"]) == payload[over]
    with pytest.raises(SchemaValidationError, match="Directional"):
        PairedCountComparisonResponse.model_validate(payload)


def test_saved_global_organism_votes_reject_relabeling_without_units() -> None:
    """Even ungrouped comparisons cannot relabel all organism directions."""
    from reefvision.schemas.model_agreement import PairedCountComparisonResponse

    pairs = [
        pair("a", "frag-A", "tank-1", 10, 12),
        pair("b", "frag-B", "tank-1", 10, 13),
    ]
    for observation in pairs:
        observation.pop("experimental_unit_id")
        observation.pop("experimental_unit_type")
    result = compare_paired_counts(
        PairedCountComparisonRequest(reference_kind="human_observer", pairs=pairs)
    )
    payload = result.model_dump(mode="json")
    payload["overcount_organism_count"] = 0
    payload["undercount_organism_count"] = 2
    with pytest.raises(SchemaValidationError, match="Directional"):
        PairedCountComparisonResponse.model_validate(payload)


def test_saved_global_repeat_imbalance_flag_must_match_rows() -> None:
    """Repeated organism images must not be hidden by changing a boolean flag."""
    from reefvision.schemas.model_agreement import PairedCountComparisonResponse

    result = compare_paired_counts(
        PairedCountComparisonRequest(
            reference_kind="human_consensus",
            pairs=[
                pair("a", "frag-A", "tank-1", 10, 12),
                pair("b", "frag-A", "tank-1", 10, 9),
                pair("c", "frag-B", "tank-1", 10, 11),
            ],
        )
    )
    payload = result.model_dump(mode="json")
    assert payload["unequal_pair_counts_across_organisms"] is True
    payload["unequal_pair_counts_across_organisms"] = False
    with pytest.raises(SchemaValidationError, match="Directional"):
        PairedCountComparisonResponse.model_validate(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_observation",
        "duplicate_reference_source",
        "duplicate_model_source",
        "cross_role_source_reuse",
        "fractional_reference_and_model",
    ],
)
def test_current_saved_paired_rows_preserve_source_uniqueness_and_integer_counts(
    mutation: str,
) -> None:
    """Even arithmetic-consistent saved rows cannot manufacture source evidence."""
    from reefvision.schemas.model_agreement import PairedCountComparisonResponse

    rows = [
        pair("a", "frag-A", "tank-1", 10, 10),
        pair("b", "frag-B", "tank-1", 20, 20),
    ]
    for row in rows:
        row.pop("experimental_unit_id")
        row.pop("experimental_unit_type")
    result = compare_paired_counts(
        PairedCountComparisonRequest(reference_kind="human_consensus", pairs=rows)
    )
    payload = result.model_dump(mode="json")
    first, second = payload["paired_differences"]
    if mutation == "duplicate_observation":
        second["observation_id"] = first["observation_id"]
    elif mutation == "duplicate_reference_source":
        second["reference_source_record_id"] = first["reference_source_record_id"]
    elif mutation == "duplicate_model_source":
        second["model_source_record_id"] = first["model_source_record_id"]
    elif mutation == "cross_role_source_reuse":
        second["model_source_record_id"] = first["reference_source_record_id"]
    else:
        # Both raw counts change together: signed/absolute differences,
        # percentages, directional votes and all aggregate means stay exact.
        first["reference_count"] = 10.5
        first["model_count"] = 10.5
    with pytest.raises(SchemaValidationError, match="Directional"):
        PairedCountComparisonResponse.model_validate(payload)


@pytest.mark.parametrize("field", ["reference_count", "model_count"])
def test_saved_paired_counts_reject_unsafe_integral_floats(field: str) -> None:
    """Persisted rows cannot manufacture enormous exact-match raw counts."""
    from reefvision.schemas.model_agreement import PairedCountComparisonResponse

    rows = [
        pair("a", "frag-A", "tank-1", 10, 10),
        pair("b", "frag-B", "tank-2", 20, 20),
    ]
    result = compare_paired_counts(
        PairedCountComparisonRequest(reference_kind="human_consensus", pairs=rows)
    )
    payload = result.model_dump(mode="json")
    payload["paired_differences"][0][field] = float(2**53)
    with pytest.raises(SchemaValidationError, match="safe-integer range"):
        PairedCountComparisonResponse.model_validate(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_source",
        "fabricated_source",
        "reordered_sources",
        "invented_independent_units",
        "invented_percent_eligible_units",
        "invented_percent_eligible_organisms",
    ],
)
def test_saved_comparison_rejects_forged_source_roster_and_unregistered_n(
    mutation: str,
) -> None:
    """A saved descriptive result cannot invent provenance or biological replication."""
    from reefvision.schemas.model_agreement import PairedCountComparisonResponse

    observations = [
        pair("a", "frag-A", "tank-1", 10, 12),
        pair("b", "frag-B", "tank-2", 20, 20),
    ]
    for observation in observations:
        observation.pop("experimental_unit_id")
        observation.pop("experimental_unit_type")
    comparison = compare_paired_counts(
        PairedCountComparisonRequest(reference_kind="human_consensus", pairs=observations)
    )
    payload = comparison.model_dump(mode="json")
    assert payload["declared_independent_unit_count"] is None
    assert payload["percent_contributing_independent_unit_count"] is None
    assert payload["percent_contributing_organism_count"] is None
    if mutation == "missing_source":
        payload["analysis_provenance"]["source_record_ids"].pop()
    elif mutation == "fabricated_source":
        payload["analysis_provenance"]["source_record_ids"][0] = "fabricated-human-source"
    elif mutation == "reordered_sources":
        payload["analysis_provenance"]["source_record_ids"].reverse()
    elif mutation == "invented_independent_units":
        payload["declared_independent_unit_count"] = 2
    elif mutation == "invented_percent_eligible_units":
        payload["percent_contributing_independent_unit_count"] = 2
    else:
        payload["percent_contributing_organism_count"] = 2
    with pytest.raises(SchemaValidationError, match="Directional"):
        PairedCountComparisonResponse.model_validate(payload)


@pytest.mark.parametrize("field", ["reference_count", "model_count"])
@pytest.mark.parametrize("coerced_value", [True, "10"])
def test_saved_current_comparison_rejects_coerced_raw_count_types(
    field: str, coerced_value: object
) -> None:
    """A saved result cannot disguise a Boolean or string as a raw count."""
    from reefvision.schemas.model_agreement import PairedCountComparisonResponse

    observations = [
        pair("a", "frag-A", "tank-1", 10, 12),
        pair("b", "frag-B", "tank-2", 20, 20),
    ]
    comparison = compare_paired_counts(
        PairedCountComparisonRequest(reference_kind="human_consensus", pairs=observations)
    )
    payload = comparison.model_dump(mode="json")
    payload["paired_differences"][0][field] = coerced_value
    with pytest.raises(SchemaValidationError, match="Directional persisted raw counts"):
        PairedCountComparisonResponse.model_validate(payload)


@pytest.mark.parametrize(
    "mutation",
    ["reverse_rows", "padded_observation_id", "blank_observation_id"],
)
def test_current_saved_comparison_requires_canonical_paired_identity(
    mutation: str,
) -> None:
    """Saved source order and canonical IDs must agree with reproducible reports."""
    from reefvision.schemas.model_agreement import PairedCountComparisonResponse

    observations = [
        pair("a", "frag-A", "tank-1", 10, 12),
        pair("b", "frag-B", "tank-2", 20, 20),
    ]
    result = compare_paired_counts(
        PairedCountComparisonRequest(reference_kind="human_consensus", pairs=observations)
    )
    payload = result.model_dump(mode="json")
    assert PairedCountComparisonResponse.model_validate(payload).paired_observation_count == 2
    if mutation == "reverse_rows":
        payload["paired_differences"].reverse()
    elif mutation == "padded_observation_id":
        payload["paired_differences"][0]["observation_id"] = " a "
    else:
        payload["paired_differences"][0]["observation_id"] = " "
    with pytest.raises(SchemaValidationError, match="Directional paired"):
        PairedCountComparisonResponse.model_validate(payload)


def test_historical_comparison_retains_previous_numeric_decoding() -> None:
    """Read-only compatibility for pre-0007 unverified saved artifacts."""
    from reefvision.schemas.model_agreement import PairedCountComparisonResponse

    observations = [
        pair("a", "frag-A", "tank-1", 10, 12),
        pair("b", "frag-B", "tank-2", 20, 20),
    ]
    comparison = compare_paired_counts(
        PairedCountComparisonRequest(reference_kind="human_consensus", pairs=observations)
    )
    payload = comparison.model_dump(mode="json")
    payload["analysis_provenance"]["algorithm_version"] = "ecology-paired-count-0006"
    payload["paired_differences"][0]["reference_count"] = "10"
    restored = PairedCountComparisonResponse.model_validate(payload)
    assert restored.paired_differences[0].reference_count == 10
