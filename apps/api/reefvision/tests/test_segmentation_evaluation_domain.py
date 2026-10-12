"""Scientific mask metrics must never silently fall back to bounding boxes."""

from __future__ import annotations

import pytest

from reefvision.domain.segmentation_evaluation import (
    ScoredInstanceMask,
    instance_mask_metrics,
    mask_iou,
)


def mask(
    runs: tuple[tuple[int, int, int], ...] = ((1, 1, 3), (2, 1, 3)),
    *,
    image: str = "image-a",
    label: str = "coral",
    confidence: float = 1.0,
    width: int = 8,
    height: int = 8,
) -> ScoredInstanceMask:
    return ScoredInstanceMask(image, label, confidence, width, height, runs)


def test_perfect_instance_mask_has_perfect_mask_ap50_and_count() -> None:
    result = instance_mask_metrics([mask()], [mask(confidence=0.9)], image_count=1)
    assert result.mask_map50 == 1
    assert result.precision == 1
    assert result.recall == 1
    assert result.mean_matched_mask_iou == 1
    assert result.count_bias_per_image == 0
    assert result.mean_absolute_count_error == 0


def test_pixelwise_iou_excludes_holes_even_when_bounding_boxes_match() -> None:
    hollow = mask(((1, 1, 5), (2, 1, 2), (2, 4, 5), (3, 1, 5)))
    filled = mask(((1, 1, 5), (2, 1, 5), (3, 1, 5)))
    assert mask_iou(hollow, filled) == pytest.approx(10 / 12)
    assert mask_iou(filled, hollow) == pytest.approx(10 / 12)


def test_disconnected_regions_count_only_true_pixels() -> None:
    a = mask(((0, 0, 2), (0, 4, 6)))
    b = mask(((0, 1, 5),))
    assert mask_iou(a, b) == pytest.approx(2 / 6)


def test_same_box_but_disjoint_masks_cannot_match() -> None:
    truth = mask(((0, 0, 1), (1, 2, 3)))
    prediction = mask(((0, 2, 3), (1, 0, 1)))
    assert mask_iou(truth, prediction) == 0
    result = instance_mask_metrics([truth], [prediction], image_count=1)
    assert result.mask_map50 == 0
    assert result.precision == 0
    assert result.recall == 0


def test_duplicate_instance_masks_are_false_positives() -> None:
    item = mask()
    result = instance_mask_metrics(
        [item], [mask(confidence=0.95), mask(confidence=0.8)], image_count=1
    )
    assert result.per_class["coral"].true_positives == 1
    assert result.per_class["coral"].false_positives == 1
    assert result.precision == 0.5
    assert result.recall == 1
    assert result.count_bias_per_image == 1
    assert result.mean_absolute_count_error == 1


def test_wrong_class_or_image_never_matches() -> None:
    ground = mask()
    result = instance_mask_metrics(
        [ground],
        [mask(label="fish"), mask(image="image-b")],
        image_count=2,
    )
    assert result.per_class["coral"].false_negatives == 1
    assert result.per_class["fish"].false_positives == 1
    assert result.precision == 0
    assert result.mask_map50 == 0
    assert mask_iou(ground, mask(image="image-b")) == 0


def test_confidence_operating_point_does_not_change_all_scores_ap() -> None:
    low = mask(confidence=0.1)
    result = instance_mask_metrics([mask()], [low], image_count=1)
    assert result.mask_map50 == 1
    assert result.precision == 0
    assert result.recall == 0
    assert result.count_bias_per_image == -1


def test_empty_predictions_have_count_error_and_zero_ap() -> None:
    result = instance_mask_metrics([mask()], [], image_count=3)
    assert result.mask_map50 == 0
    assert result.recall == 0
    assert result.mean_absolute_count_error == pytest.approx(1 / 3)


@pytest.mark.parametrize(
    "runs",
    [
        (),
        ((0, 0, 0),),
        ((0, 0, 9),),
        ((8, 0, 1),),
        ((1, 1, 4), (1, 3, 5)),
        ((2, 0, 2), (1, 0, 2)),
    ],
)
def test_invalid_or_overlapping_run_geometry_fails_closed(
    runs: tuple[tuple[int, int, int], ...],
) -> None:
    with pytest.raises(ValueError):
        mask(runs)


def test_inconsistent_source_geometry_or_count_fails_closed() -> None:
    with pytest.raises(ValueError, match="same source dimensions"):
        mask_iou(mask(), mask(width=9))
    with pytest.raises(ValueError, match="Inconsistent dimensions"):
        instance_mask_metrics([mask()], [mask(width=9)], image_count=1)
    with pytest.raises(ValueError, match="image IDs exceed"):
        instance_mask_metrics([mask(image="a"), mask(image="b")], [], image_count=1)


def test_invalid_threshold_and_nonfinite_confidence_fail_closed() -> None:
    with pytest.raises(ValueError, match="confidence"):
        mask(confidence=float("nan"))
    with pytest.raises(ValueError, match="metric threshold"):
        instance_mask_metrics([], [], image_count=1, iou_threshold=0)
    with pytest.raises(ValueError, match="metric threshold"):
        instance_mask_metrics([], [], image_count=0)
