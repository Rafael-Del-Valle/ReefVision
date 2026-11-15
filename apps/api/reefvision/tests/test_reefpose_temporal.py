from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

import pytest

torch = pytest.importorskip("torch")


def _sequence(
    xs: Sequence[float | None],
    *,
    recording: str = "video-a",
    group: str = "session-a",
    targets: Sequence[float | None] | None = None,
):
    from reefvision.ml.reefpose.temporal import TemporalFrame, TemporalPoint, TemporalSequence

    return TemporalSequence(
        recording_id=recording,
        animal_id="subject-a",
        group_key=group,
        schema_hash="skeleton-a",
        width=100,
        height=50,
        frames=tuple(
            TemporalFrame(
                frame_index=index,
                timestamp_seconds=index * 0.125,
                observations=(TemporalPoint(x, 12.5, 0.8, "visible"),) if x is not None else None,
                targets=(TemporalPoint(target, 12.5, None, "visible"),)
                if targets is not None and (target := targets[index]) is not None
                else None,
            )
            for index, x in enumerate(xs)
        ),
    )


@pytest.fixture(autouse=True)
def _small_tensor_thread_pool():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def test_pixel_normalization_is_invertible_on_nonsquare_media() -> None:
    from reefvision.ml.reefpose.temporal import denormalize_point, normalize_point

    assert normalize_point(25, 37.5, width=100, height=50) == (-0.5, 0.5)
    assert denormalize_point(-0.5, 0.5, width=100, height=50) == (25, 37.5)


def test_inference_batch_budget_accounts_for_long_anatomy_windows() -> None:
    from reefvision.ml.reefpose.temporal import TemporalConfig

    config = TemporalConfig(1024, window_length=129)
    assert config.effective_batch_size(128) == 1
    assert config.input_tensor_byte_bound(128) == 5_294_096


def test_training_rejects_recording_crossing_independent_split_groups() -> None:
    from reefvision.ml.reefpose.errors import ReefPoseValidationError
    from reefvision.ml.reefpose.temporal import (
        TemporalConfig,
        TemporalTrainingConfig,
        train_temporal,
    )

    train = _sequence([20], targets=[15])
    validation = replace(train, animal_id="subject-b", group_key="session-b")
    with pytest.raises(ReefPoseValidationError, match="recording"):
        train_temporal(
            (train, validation),
            {"session-a": "train", "session-b": "validation"},
            TemporalConfig(num_keypoints=1),
            TemporalTrainingConfig(epochs=1, device="cpu"),
        )


def test_context_is_bounded_by_declared_discontinuities_and_elapsed_gaps() -> None:
    from reefvision.ml.reefpose.temporal import TemporalConfig, TemporalRefiner, iter_refined

    sequence = _sequence([20, None, 70, None, 85])
    frames = sequence.frames
    sequence = replace(
        sequence,
        frames=(
            frames[0],
            replace(frames[1], discontinuity=True),
            replace(frames[2], timestamp_seconds=2),
            replace(frames[3], timestamp_seconds=2.5),
            replace(frames[4], timestamp_seconds=3.5),
        ),
    )
    model = TemporalRefiner(TemporalConfig(1, window_length=5, max_gap_seconds=0.75))
    results = list(iter_refined(model, sequence))
    assert results[0].future_frames == 0
    assert results[1].points == (None,)
    assert (results[2].future_frames, results[2].future_seconds) == (1, 0.5)
    assert results[3].points[0].visibility == "uncertain"
    assert results[3].points[0].confidence is None
    assert results[3].future_frames == 0


def test_causal_output_is_independent_of_future_observations() -> None:
    from reefvision.ml.reefpose.temporal import TemporalConfig, TemporalRefiner, iter_refined

    torch.manual_seed(41)
    sequence = _sequence([25, None, 35, 45, 50, 55])
    changed_future = _sequence([25, None, 35, 10, 15, 5])
    model = TemporalRefiner(TemporalConfig(1, window_length=5, context_mode="causal"))
    first = list(iter_refined(model, sequence))
    second = list(iter_refined(model, changed_future))
    assert first[:3] == second[:3]
    assert all(row.future_frames == 0 and row.future_seconds == 0 for row in first)
    assert first[3].points != second[3].points
    assert first[1].points[0].visibility == "uncertain"


def test_refinement_does_not_inspect_supervision_or_later_causal_observations() -> None:
    from reefvision.ml.reefpose.errors import ReefPoseValidationError
    from reefvision.ml.reefpose.temporal import TemporalConfig, TemporalRefiner, iter_refined

    sequence = _sequence([25, 30, 35])
    first, second, later = sequence.frames
    sequence = replace(
        sequence,
        frames=(replace(first, targets=()), second, replace(later, observations=())),
    )
    model = TemporalRefiner(TemporalConfig(1, window_length=3, context_mode="causal"))
    predictions = iter_refined(model, sequence, chunk_size=1)
    assert next(predictions).frame_index == 0
    assert next(predictions).frame_index == 1
    with pytest.raises(ReefPoseValidationError, match="anatomy schema"):
        next(predictions)


@pytest.mark.parametrize("device", ["cpu", "cuda"])
def test_chunked_inference_matches_one_batch_with_boundary_context(device: str) -> None:
    from reefvision.ml.reefpose.temporal import TemporalConfig, TemporalRefiner, iter_refined

    if device == "cuda" and not torch.cuda.is_available():
        pytest.skip("CUDA unavailable")
    sequence = _sequence([5, 20, None, 45, 48, None, 90, 95, 98])
    model = TemporalRefiner(TemporalConfig(1, window_length=5)).to(device)
    one = list(iter_refined(model, sequence, chunk_size=99))
    many = list(iter_refined(model, sequence, chunk_size=2))
    assert [(row.frame_index, row.future_frames, row.future_seconds) for row in many] == [
        (row.frame_index, row.future_frames, row.future_seconds) for row in one
    ]
    assert [row.points[0].x for row in many] == pytest.approx([row.points[0].x for row in one])
    assert [row.points[0].y for row in many] == pytest.approx([row.points[0].y for row in one])


@pytest.mark.parametrize("device", ["cpu", "cuda"])
def test_training_uses_partial_reviewed_targets_and_resume_matches_uninterrupted(
    device: str,
) -> None:
    from reefvision.ml.reefpose.temporal import (
        TemporalConfig,
        TemporalTrainingConfig,
        iter_refined,
        load_temporal_model,
        train_temporal,
    )

    if device == "cuda" and not torch.cuda.is_available():
        pytest.skip("CUDA unavailable")
    sequence = _sequence([20, 20, 20, 20, 20, 20], targets=[60, None, 60, None, 60, None])
    splits = {"session-a": "train"}
    config = TemporalConfig(1, window_length=3, channels=8)
    parameters = TemporalTrainingConfig(epochs=16, batch_size=3, learning_rate=0.02, device=device)
    full = train_temporal([sequence], splits, config, parameters)
    partial = train_temporal([sequence], splits, config, replace(parameters, epochs=5))
    resumed = train_temporal([sequence], splits, config, parameters, resume=partial.state)
    assert full.state["global_step"] == resumed.state["global_step"] == 16
    assert resumed.metrics_history[-1]["train_supervised_points"] == 3
    assert resumed.metrics_history[-1]["train_loss"] < resumed.metrics_history[0]["train_loss"]
    restored = load_temporal_model(resumed.state)
    final = list(iter_refined(full.model, sequence))
    actual = list(iter_refined(restored, sequence))
    assert [row.points[0].x for row in actual] == pytest.approx(
        [row.points[0].x for row in final], abs=1e-3
    )
    assert abs(actual[2].points[0].x - 60) < abs(20 - 60)


def test_training_and_inference_honor_cancellation_at_boundaries() -> None:
    from reefvision.ml.reefpose.errors import ReefPoseCancelledError
    from reefvision.ml.reefpose.temporal import (
        TemporalConfig,
        TemporalRefiner,
        TemporalTrainingConfig,
        iter_refined,
        train_temporal,
    )

    sequence = _sequence([20, 30], targets=[20, 30])
    config = TemporalConfig(1, window_length=3)
    with pytest.raises(ReefPoseCancelledError):
        train_temporal(
            [sequence],
            {"session-a": "train"},
            config,
            TemporalTrainingConfig(epochs=1),
            cancelled=lambda: True,
        )
    with pytest.raises(ReefPoseCancelledError):
        list(iter_refined(TemporalRefiner(config), sequence, cancelled=lambda: True))


def test_checkpoint_schema_and_configuration_validation() -> None:
    from reefvision.ml.reefpose.errors import ReefPoseValidationError
    from reefvision.ml.reefpose.temporal import (
        TemporalConfig,
        TemporalTrainingConfig,
        iter_refined,
        train_temporal,
    )

    with pytest.raises(ReefPoseValidationError):
        TemporalConfig(1, window_length=4, context_mode="centered")
    sequence = _sequence([20, 25], targets=[20, 25])
    result = train_temporal(
        [sequence],
        {"session-a": "train"},
        TemporalConfig(1),
        TemporalTrainingConfig(epochs=1, device="cpu"),
    )
    with pytest.raises(ReefPoseValidationError, match="schema"):
        list(iter_refined(result.model, replace(sequence, schema_hash="other")))
