from __future__ import annotations

import pytest

from reefvision.ml.reefpose.temporal_data import (
    TemporalFrame,
    TemporalFrameResult,
    TemporalPoint,
    TemporalSequence,
)


def _point(x: float, visibility: str = "visible") -> TemporalPoint:
    return TemporalPoint(x, 0, visibility=visibility)


def _series(
    recording: str,
    reference: list[TemporalPoint],
    observed: list[TemporalPoint | None],
    predictions: list[TemporalPoint | None],
) -> tuple[TemporalSequence, list[TemporalFrameResult]]:
    rows: list[TemporalFrame] = []
    refined: list[TemporalFrameResult] = []
    for index, (target, observation, prediction) in enumerate(
        zip(reference, observed, predictions, strict=True)
    ):
        timestamp = float(index)
        rows.append(
            TemporalFrame(index, timestamp, (observation,) if observation else None, (target,))
        )
        refined.append(TemporalFrameResult(index, timestamp, (prediction,), 0, 0.0))
    return TemporalSequence(recording, "animal", recording, "schema", 80, 60, tuple(rows)), refined


def test_paired_landmark_metrics_report_occlusion_and_grouped_uncertainty() -> None:
    from reefvision.ml.reefpose.temporal_metrics import evaluate_temporal_predictions

    sequences = []
    predictions = {}
    for index in range(5):
        sequence, refined = _series(
            f"recording-{index}",
            [_point(10), _point(10, "occluded"), _point(10)],
            [_point(10), _point(14), None],
            [_point(10), _point(11), _point(10, "uncertain")],
        )
        sequences.append(sequence)
        predictions[(sequence.recording_id, sequence.animal_id)] = refined
    result = evaluate_temporal_predictions(sequences, predictions, bootstrap_samples=50)
    assert result["counts"]["groups"] == 5
    assert result["landmarks"]["frame_only"]["missing_coordinates"] == 5
    assert result["landmarks"]["refined"]["missing_coordinates"] == 0
    assert result["landmarks"]["refined"]["by_visibility"]["occluded"]["mean_error_px"] == 1.0
    paired = result["landmarks"]["paired"]
    assert paired["count"] == 10
    assert paired["mean_delta_px"] == -1.5
    assert paired["cluster_interval_95_px"] == [-1.5, -1.5]
    assert result["trajectory"]["stationary"]["count"] == 5
    assert result["trajectory"]["stationary"]["frame_only"]["mean_speed_px_per_second"] == 4.0
    assert result["trajectory"]["stationary"]["refined"]["mean_speed_px_per_second"] == 1.0


def test_rapid_motion_report_measures_attenuation_and_late_proxy_onset() -> None:
    from reefvision.ml.reefpose.temporal_metrics import evaluate_temporal_predictions

    sequence, refined = _series(
        "recording-a",
        [_point(x) for x in (10, 10, 40, 70, 70)],
        [_point(x) for x in (10, 10, 40, 70, 70)],
        [_point(x) for x in (10, 10, 15, 45, 45)],
    )
    result = evaluate_temporal_predictions([sequence], {("recording-a", "animal"): refined})
    assert result["trajectory"]["rapid"]["refined"]["mean_speed_bias_px_per_second"] == -12.5
    assert result["movement"]["reference_events"] == 1
    assert result["movement"]["refined"]["count_error"] == 0
    assert result["movement"]["refined"]["matched_events"] == 1
    assert result["movement"]["refined"]["mean_onset_error_seconds"] == 1.0
    assert result["landmarks"]["paired"]["cluster_interval_95_px"] is None


def test_anatomical_metric_uses_source_pixel_landmark_pairs_and_shared_support() -> None:
    from reefvision.ml.reefpose.temporal_metrics import evaluate_temporal_predictions

    sequence = TemporalSequence(
        "video",
        "animal",
        "session",
        "schema",
        100,
        50,
        (
            TemporalFrame(0, 0, (_point(10), _point(28)), (_point(10), _point(30))),
            TemporalFrame(1, 1, (_point(10), _point(28)), (_point(10), _point(30))),
        ),
    )
    refined = [
        TemporalFrameResult(0, 0, (_point(11), _point(30)), 0, 0),
        TemporalFrameResult(1, 1, (_point(11), None), 0, 0),
    ]
    result = evaluate_temporal_predictions(
        [sequence],
        {("video", "animal"): refined},
        skeleton_edges=[(0, 1)],
    )["anatomical"]["paired"]
    assert result["count"] == 1
    assert result["frame_only_mean_error_px"] == 2
    assert result["refined_mean_error_px"] == 1


def _motion_series(
    truth: list[float],
    observed: list[float | None],
    *,
    breaks: set[int] | None = None,
    actual_times: list[float] | None = None,
) -> tuple[TemporalSequence, list[TemporalFrameResult]]:
    frames = []
    refined = []
    for index, (target, observation) in enumerate(zip(truth, observed, strict=True)):
        time = actual_times[index] if actual_times is not None else index / 10
        target_points = (_point(0), _point(target))
        observed_points = (
            _point(0),
            _point(observation) if observation is not None else TemporalPoint(),
        )
        frames.append(
            TemporalFrame(index, time, observed_points, target_points, index in (breaks or set()))
        )
        refined.append(TemporalFrameResult(index, time, target_points, 0, 0))
    return TemporalSequence("video", "animal", "session", "schema", 100, 50, tuple(frames)), refined


def test_anatomical_hysteresis_scores_only_complete_cycles_on_shared_support() -> None:
    from reefvision.domain.pose_biological_events import CycleDefinition
    from reefvision.ml.reefpose.temporal_events import AnatomicalEventConfig
    from reefvision.ml.reefpose.temporal_metrics import evaluate_temporal_predictions

    sequence, refined = _motion_series(
        [2, 9, 12, 3, 2, 10, 12, 3, 2, 9, 12, 3],
        [2, 4, 10, 3, 2, 10, 12, 3, 2, None, 12, 3],
    )
    result = evaluate_temporal_predictions(
        [sequence],
        {("video", "animal"): refined},
        anatomical_events=AnatomicalEventConfig(
            ("lip_upper", "lip_lower"),
            (0, 1),
            CycleDefinition(8, 3),
        ),
    )["anatomical_events"]
    assert result["derivation"]["landmark_ids"] == ["lip_upper", "lip_lower"]
    assert result["support"]["common_frames"] == 11
    assert result["support"]["frame_only_missing_frames"] == 1
    assert result["support"]["evaluated_seconds"] == pytest.approx(0.9)
    assert result["reference"]["complete_events"] == 2
    assert result["reference"]["partial_candidates"] == 1
    assert result["frame_only"]["count_error"] == 0
    assert result["frame_only"]["timing_errors"]["onset_error_s"]["bias"] == pytest.approx(0.05)
    assert result["refined"]["timing_errors"]["onset_error_s"]["mae"] == 0


def test_anatomical_cycles_do_not_bridge_discontinuities_or_time_gaps() -> None:
    from reefvision.domain.pose_biological_events import CycleDefinition
    from reefvision.ml.reefpose.temporal_events import AnatomicalEventConfig
    from reefvision.ml.reefpose.temporal_metrics import evaluate_temporal_predictions

    sequence, refined = _motion_series(
        [2, 9, 3, 2, 9, 3],
        [2, 9, 3, 2, 9, 3],
        breaks={2},
        actual_times=[0, 0.1, 0.2, 0.3, 0.4, 1.2],
    )
    result = evaluate_temporal_predictions(
        [sequence],
        {("video", "animal"): refined},
        anatomical_events=AnatomicalEventConfig(
            ("lip_upper", "lip_lower"),
            (0, 1),
            CycleDefinition(8, 3),
        ),
    )["anatomical_events"]
    assert result["support"]["common_support_segments"] == 3
    assert result["support"]["evaluated_seconds"] == pytest.approx(0.3)
    assert result["reference"]["complete_events"] == 0
    assert result["reference"]["partial_candidates"] == 2
    assert result["refined"]["timing_errors"]["offset_error_s"]["n"] == 0
