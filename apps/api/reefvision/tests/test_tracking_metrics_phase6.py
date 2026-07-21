from __future__ import annotations

import pytest

from reefvision.ml.tracking_metrics import TrackBox, evaluate_tracking


def _box(frame: int, track_id: str, x: float, *, depth: float = 1.0) -> TrackBox:
    return TrackBox(
        frame_index=frame,
        track_id=track_id,
        x=x,
        y=10,
        width=10,
        height=6,
        confidence=0.9,
        depth=depth,
    )


def test_perfect_tracking_reports_full_detection_and_identity_scores() -> None:
    references = [_box(frame, "fish-a", frame * 2) for frame in range(10)]
    predictions = [_box(frame, "pred-a", frame * 2) for frame in range(10)]
    metrics = evaluate_tracking(references, predictions, minimum_iou=0.5)

    assert metrics.false_positive_count == 0
    assert metrics.false_negative_count == 0
    assert metrics.identity_switch_count == 0
    assert metrics.fragmentation_count == 0
    assert metrics.mota == pytest.approx(1)
    assert metrics.motp == pytest.approx(1)
    assert metrics.idf1 == pytest.approx(1)
    assert metrics.hota == pytest.approx(1)
    assert metrics.mean_track_continuity == pytest.approx(1)


def test_identity_switch_fragmentation_and_depth_gating_are_quantified() -> None:
    references = [_box(frame, "fish-a", frame, depth=0.8) for frame in range(8)]
    predictions = [
        _box(frame, "pred-a" if frame < 3 else "pred-b", frame, depth=0.8)
        for frame in range(8)
        if frame != 4
    ]
    metrics = evaluate_tracking(references, predictions, minimum_iou=0.5)

    assert metrics.identity_switch_count == 1
    assert metrics.fragmentation_count == 1
    assert metrics.false_negative_count == 1
    assert metrics.mota < 1
    assert metrics.mean_track_continuity == pytest.approx(0.5)

    wrong_depth = [_box(frame, "pred-a", frame, depth=2.5) for frame in range(8)]
    gated = evaluate_tracking(
        references,
        wrong_depth,
        minimum_iou=0.5,
        maximum_depth_gap=0.5,
    )
    assert gated.matched_detection_count == 0
    assert gated.false_positive_count == 8
    assert gated.false_negative_count == 8


def test_false_positive_and_false_negative_tracks_are_reported() -> None:
    references = [
        *[_box(frame, "fish-a", frame) for frame in range(3)],
        *[_box(frame, "fish-b", 50 + frame) for frame in range(3)],
    ]
    predictions = [
        *[_box(frame, "pred-a", frame) for frame in range(3)],
        *[_box(frame, "pred-extra", 80 + frame) for frame in range(3)],
    ]

    metrics = evaluate_tracking(references, predictions, minimum_iou=0.5)

    assert metrics.false_positive_count == 3
    assert metrics.false_negative_count == 3
    assert metrics.false_positive_track_count == 1
    assert metrics.false_negative_track_count == 1
    assert metrics.detection_precision == pytest.approx(0.5)
    assert metrics.detection_recall == pytest.approx(0.5)
    assert metrics.mostly_tracked_count == 1
    assert metrics.mostly_lost_count == 1
    assert {item.reference_track_id: item.coverage for item in metrics.per_track} == {
        "fish-a": pytest.approx(1),
        "fish-b": pytest.approx(0),
    }
