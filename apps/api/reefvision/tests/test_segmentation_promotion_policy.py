"""Regression tests for scientific segmentation candidate eligibility guardrails."""

import pytest

from reefvision.domain.segmentation_promotion_policy import (
    SegmentationCandidateScore,
    candidate_meets_segmentation_guardrails,
)


def score(model: str, ap: float, error: float, **changes: object) -> SegmentationCandidateScore:
    fields = dict(
        model_id=model,
        project_id="p",
        dataset_version_id="v",
        split_digest="immutable-holdout",
        mask_map50=ap,
        mean_absolute_count_error=error,
        evaluated_images=12,
    )
    fields.update(changes)
    return SegmentationCandidateScore(**fields)


def test_improved_mask_ap_without_count_degradation_is_eligible() -> None:
    assert candidate_meets_segmentation_guardrails(
        score("candidate", 0.85, 1.0),
        score("incumbent", 0.75, 1.0),
        minimum_mask_map50=0.7,
        minimum_gain=0.05,
    )


def test_worse_count_error_blocks_even_if_mask_ap_improves() -> None:
    assert not candidate_meets_segmentation_guardrails(
        score("candidate", 0.95, 1.1),
        score("incumbent", 0.75, 1.0),
        minimum_mask_map50=0.7,
    )


def test_quality_floor_and_gain_both_apply() -> None:
    incumbent = score("incumbent", 0.7, 1.0)
    assert not candidate_meets_segmentation_guardrails(
        score("candidate", 0.75, 1.0),
        incumbent,
        minimum_mask_map50=0.8,
    )
    assert not candidate_meets_segmentation_guardrails(
        score("candidate", 0.75, 1.0), incumbent,
        minimum_mask_map50=0.7,
        minimum_gain=0.1,
    )


@pytest.mark.parametrize(
    "change",
    [
        {"project_id": "other"},
        {"dataset_version_id": "new"},
        {"split_digest": "different"},
        {"evaluated_images": 11},
    ],
)
def test_incompatible_holdout_fails_closed(change: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="same immutable evaluation split"):
        candidate_meets_segmentation_guardrails(
            score("candidate", 0.9, 0.5, **change),
            score("incumbent", 0.7, 1.0),
            minimum_mask_map50=0.6,
        )


def test_initial_activation_still_requires_quality_floor() -> None:
    assert not candidate_meets_segmentation_guardrails(
        score("candidate", 0.4, 0.5),
        None,
        minimum_mask_map50=0.5,
    )


@pytest.mark.parametrize("ap,error", [(float("nan"), 0.0), (0.5, -1.0), (1.1, 0.0)])
def test_invalid_scores_rejected(ap: float, error: float) -> None:
    with pytest.raises(ValueError):
        score("candidate", ap, error)


def test_invalid_threshold_rejected() -> None:
    with pytest.raises(ValueError, match="threshold"):
        candidate_meets_segmentation_guardrails(
            score("candidate", 0.8, 1.0),
            None,
            minimum_mask_map50=float("nan"),
        )
