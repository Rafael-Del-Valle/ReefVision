import pytest

from reefvision.domain.reefpose_agreement import (
    ScoredEvent,
    cluster_interval,
    event_agreement,
    icc_absolute,
    measurement_agreement,
)


def test_event_match_maximizes_cardinality_before_timing_cost() -> None:
    truth = [ScoredEvent("a", 1, 2), ScoredEvent("b", 1.25, 2.25)]
    predicted = [
        ScoredEvent("p1", 1.12, 2.12),
        ScoredEvent("p2", 0.85, 1.85),
        ScoredEvent("partial", 1, 2, state="partial"),
    ]
    result = event_agreement(truth, predicted, 0.2, 0.2)
    assert (result["tp"], result["fp"], result["fn"]) == (2, 1, 0)
    assert result["f1"] == pytest.approx(0.8)
    assert [(row["reference"], row["prediction"]) for row in result["matches"]] == [
        ("a", "p2"),
        ("b", "p1"),
    ]


def test_measurement_bias_and_circular_error() -> None:
    result = measurement_agreement([(10, 12), (20, 24)])
    assert result["bias"] == 3
    assert result["mae"] == 3
    assert result["rmse"] == pytest.approx(10**0.5)
    assert measurement_agreement([(179, -179)], circular=True)["bias"] == 2


def test_icc_penalizes_a_constant_rater_offset() -> None:
    assert icc_absolute([[1, 1], [2, 2], [3, 3]]) == pytest.approx(1)
    assert icc_absolute([[1, 2], [2, 3], [3, 4]]) == pytest.approx(2 / 3)
    assert icc_absolute([[1, 1], [1, 1]]) is None


def test_censored_partial_has_no_fabricated_offset_or_duration() -> None:
    report = event_agreement(
        [ScoredEvent("r", 0.2, 0.4, state="partial")],
        [ScoredEvent("p", 0.2, None, peak=0.3, state="partial")],
        0,
        0,
    )
    assert report["tp"] == 1
    assert report["matches"][0]["offset_error_s"] is None
    assert report["matches"][0]["duration_error_s"] is None


def test_censored_onset_uses_observed_offset_only() -> None:
    report = event_agreement(
        [ScoredEvent("r", 0.2, 0.4, state="partial")],
        [ScoredEvent("p", 0, 0.4, state="partial", onset_observed=False)],
        0,
        0,
    )
    assert report["tp"] == 1
    assert report["matches"][0]["onset_error_s"] is None
    assert report["matches"][0]["offset_error_s"] == 0
    assert report["matches"][0]["duration_error_s"] is None


def test_uncertainty_requires_independent_groups() -> None:
    from statistics import fmean

    assert cluster_interval({"single-video": [2.0] * 1000}, fmean, 7) is None
    groups = {f"group-{i}": [2.0] * (i + 1) for i in range(5)}
    assert cluster_interval(groups, fmean, 7) == [2.0, 2.0]
