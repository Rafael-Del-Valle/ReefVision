from __future__ import annotations

import pytest

from reefvision.domain.pose_identity_evaluation import (
    IdentityObservation,
    evaluate_pose_identities,
)


def _observation(identity: str, frame: int, x: float) -> IdentityObservation:
    return IdentityObservation(
        identity_id=identity,
        frame_index=frame,
        bbox=(x, 0.0, 10.0, 10.0),
    )


def test_perfect_identity_tracking_has_unit_id_metrics() -> None:
    truth = [
        _observation(identity, frame, offset + frame)
        for identity, offset in (("truth-a", 0.0), ("truth-b", 100.0))
        for frame in range(3)
    ]
    prediction = [
        _observation(identity, frame, offset + frame)
        for identity, offset in (("pred-a", 0.0), ("pred-b", 100.0))
        for frame in range(3)
    ]

    report = evaluate_pose_identities(truth, prediction, iou_threshold=0.5)

    assert report.id_true_positives == 6
    assert report.id_false_positives == 0
    assert report.id_false_negatives == 0
    assert report.id_precision == report.id_recall == report.id_f1 == 1.0
    assert report.identity_switches == 0
    assert report.fragmentations == 0
    assert report.identity_mapping == {"truth-a": "pred-a", "truth-b": "pred-b"}


def test_crossed_predictions_count_switches_and_reduce_idf1() -> None:
    truth = [
        _observation("truth-a", 0, 0),
        _observation("truth-b", 0, 100),
        _observation("truth-a", 1, 10),
        _observation("truth-b", 1, 90),
    ]
    prediction = [
        _observation("pred-a", 0, 0),
        _observation("pred-b", 0, 100),
        _observation("pred-b", 1, 10),
        _observation("pred-a", 1, 90),
    ]

    report = evaluate_pose_identities(truth, prediction, iou_threshold=0.5)

    assert report.id_true_positives == 2
    assert report.id_false_positives == 2
    assert report.id_false_negatives == 2
    assert report.id_f1 == pytest.approx(0.5)
    assert report.identity_switches == 2
    assert report.association_failures == 2


def test_missed_middle_observation_counts_fragmentation_and_coverage() -> None:
    truth = [_observation("truth", frame, float(frame)) for frame in range(3)]
    prediction = [
        _observation("pred", 0, 0),
        _observation("pred", 2, 2),
        _observation("false-positive", 2, 100),
    ]

    report = evaluate_pose_identities(truth, prediction, iou_threshold=0.5)

    assert report.id_true_positives == 2
    assert report.id_false_negatives == 1
    assert report.id_false_positives == 1
    assert report.fragmentations == 1
    assert report.per_identity[0].coverage == pytest.approx(2 / 3)
    assert report.spatial_matches == 2
    assert report.spatial_misses == 1
    assert report.spatial_false_positives == 1


def test_evaluation_rejects_empty_or_duplicate_truth_observations() -> None:
    with pytest.raises(ValueError, match="verified ground-truth"):
        evaluate_pose_identities([], [_observation("pred", 0, 0)])

    duplicate = [_observation("truth", 0, 0), _observation("truth", 0, 1)]
    with pytest.raises(ValueError, match="one observation per identity and frame"):
        evaluate_pose_identities(duplicate, [])
