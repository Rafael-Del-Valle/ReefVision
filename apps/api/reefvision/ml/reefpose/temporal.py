"""Residual temporal convolution and native training for ReefPose observations."""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Literal, TypeVar, cast

import torch
from torch import nn
from torch.nn import functional as F

from reefvision.ml.reefpose.errors import ReefPoseCancelledError, ReefPoseValidationError
from reefvision.ml.reefpose.temporal_data import (
    ContextMode,
    TemporalFrame,
    TemporalFrameResult,
    TemporalPoint,
    TemporalSequence,
    TemporalSplit,
    denormalize_point,
    normalize_point,
    starts_segment,
    validate_max_gap,
    validate_splits,
)
from reefvision.ml.reefpose.training import resolve_device

__all__ = [
    "NORMALIZATION",
    "TEMPORAL_FORMAT",
    "TIMING_POLICY",
    "TemporalConfig",
    "TemporalFrame",
    "TemporalFrameResult",
    "TemporalPoint",
    "TemporalRefiner",
    "TemporalSequence",
    "TemporalTrainingConfig",
    "TemporalTrainingResult",
    "denormalize_point",
    "iter_refined",
    "load_temporal_model",
    "normalize_point",
    "train_temporal",
]

TEMPORAL_FORMAT = "reefpose-temporal-checkpoint-0001"
NORMALIZATION = "source-image-width-height-to-minus-one-one-v1"
TIMING_POLICY = "signed-log1p-elapsed-seconds-and-frame-index-delta-v1"
VISIBILITY_CHANNELS = ("absent", "occluded", "visible", "uncertain", "out_of_frame")
POINT_CHANNELS = 5 + len(VISIBILITY_CHANNELS)
FRAME_CHANNELS = 4
MAX_FEATURE_VALUES_PER_BATCH = 1_000_000
CancellationCheck = Callable[[], bool]
EpochCallback = Callable[[int, dict[str, float], dict[str, Any]], None]
_Item = TypeVar("_Item")


@dataclass(frozen=True, slots=True)
class TemporalConfig:
    num_keypoints: int
    window_length: int = 9
    context_mode: ContextMode = "centered"
    channels: int = 32
    max_gap_seconds: float | None = None

    def __post_init__(self) -> None:
        if type(self.num_keypoints) is not int or not 1 <= self.num_keypoints <= 1024:
            raise ReefPoseValidationError("Temporal model landmark count must be 1 to 1024")
        if type(self.window_length) is not int or not 2 <= self.window_length <= 129:
            raise ReefPoseValidationError("Temporal window length must be 2 to 129 frames")
        if self.context_mode not in {"causal", "centered"}:
            raise ReefPoseValidationError("Temporal context must be causal or centered")
        if self.context_mode == "centered" and self.window_length % 2 == 0:
            raise ReefPoseValidationError("Centered temporal context requires an odd window length")
        if type(self.channels) is not int or not 4 <= self.channels <= 256:
            raise ReefPoseValidationError("Temporal channels must be 4 to 256")
        validate_max_gap(self.max_gap_seconds)

    @property
    def future_frames(self) -> int:
        return self.window_length // 2 if self.context_mode == "centered" else 0

    @property
    def past_frames(self) -> int:
        return self.window_length - self.future_frames - 1

    @property
    def _feature_values_per_window(self) -> int:
        return self.window_length * (FRAME_CHANNELS + POINT_CHANNELS * self.num_keypoints)

    def effective_batch_size(self, requested_size: int) -> int:
        max_size = max(1, MAX_FEATURE_VALUES_PER_BATCH // self._feature_values_per_window)
        return min(requested_size, max_size)

    def input_tensor_byte_bound(self, requested_size: int) -> int:
        """Bound prepared float32 features and anchors, separate from activations."""
        values_per_item = self._feature_values_per_window + 2 * self.num_keypoints
        return self.effective_batch_size(requested_size) * values_per_item * 4


@dataclass(frozen=True, slots=True)
class TemporalTrainingConfig:
    epochs: int = 20
    batch_size: int = 32
    learning_rate: float = 0.001
    loss: Literal["smooth_l1", "mse"] = "smooth_l1"
    seed: int = 1337
    device: str = "auto"
    weight_decay: float = 0.0001
    smooth_l1_beta: float = 0.1

    def __post_init__(self) -> None:
        if type(self.epochs) is not int or not 1 <= self.epochs <= 10_000:
            raise ReefPoseValidationError("Temporal training epochs must be 1 to 10,000")
        if type(self.batch_size) is not int or not 1 <= self.batch_size <= 1024:
            raise ReefPoseValidationError("Temporal batch size must be 1 to 1024")
        if type(self.seed) is not int or not 0 <= self.seed < 2**32:
            raise ReefPoseValidationError(
                "Temporal training seed must be an unsigned 32-bit integer"
            )
        if self.loss not in {"smooth_l1", "mse"}:
            raise ReefPoseValidationError("Temporal loss must be smooth_l1 or mse")
        if not math.isfinite(self.learning_rate) or self.learning_rate <= 0:
            raise ReefPoseValidationError("Temporal learning rate must be positive")
        if not math.isfinite(self.smooth_l1_beta) or self.smooth_l1_beta <= 0:
            raise ReefPoseValidationError("Temporal Smooth L1 beta must be positive")
        if not math.isfinite(self.weight_decay) or self.weight_decay < 0:
            raise ReefPoseValidationError("Temporal weight decay must be nonnegative")


class TemporalRefiner(nn.Module):
    """Predict a source-normalized offset from the nearest valid observation."""

    architecture_name = "ReefPose-TCN"
    architecture_version = 1

    def __init__(self, config: TemporalConfig, schema_hash: str | None = None) -> None:
        super().__init__()
        self.config = config
        self.schema_hash = schema_hash
        channels = config.channels
        self.input_projection = nn.Conv1d(
            config.num_keypoints * POINT_CHANNELS + FRAME_CHANNELS, channels, kernel_size=1
        )
        self.context_convolution = nn.Conv1d(channels, channels, kernel_size=config.window_length)
        self.residual_block = nn.Sequential(nn.Conv1d(channels, channels, kernel_size=1), nn.SiLU())
        self.output_projection = nn.Conv1d(channels, config.num_keypoints * 2, kernel_size=1)
        nn.init.normal_(self.output_projection.weight, std=0.001)
        bias = self.output_projection.bias
        assert bias is not None
        nn.init.zeros_(bias)

    def forward(self, features: torch.Tensor, anchors: torch.Tensor) -> torch.Tensor:
        projected = F.silu(self.input_projection(features.transpose(1, 2)))
        context = F.silu(self.context_convolution(projected))
        corrections = self.output_projection(context + self.residual_block(context))
        corrections = corrections.squeeze(-1).reshape(-1, self.config.num_keypoints, 2)
        return cast(torch.Tensor, anchors + corrections)


@dataclass(slots=True)
class _Window:
    features: list[list[float]]
    anchors: list[tuple[float, float]]
    available: list[bool]
    future_frames: int
    future_seconds: float


def _signed_log(delta: float) -> float:
    return math.copysign(math.log1p(abs(delta)), delta)


def _context_bounds(
    frames: tuple[TemporalFrame, ...], index: int, config: TemporalConfig
) -> tuple[int, int]:
    start = index
    for neighbor in range(index - 1, max(-1, index - config.past_frames - 1), -1):
        if starts_segment(frames[neighbor], frames[neighbor + 1], config.max_gap_seconds):
            break
        start = neighbor
    end = index + 1
    for neighbor in range(index + 1, min(len(frames), index + config.future_frames + 1)):
        if starts_segment(frames[neighbor - 1], frames[neighbor], config.max_gap_seconds):
            break
        end = neighbor + 1
    return start, end


def _window(sequence: TemporalSequence, index: int, config: TemporalConfig) -> _Window:
    frames = sequence.frames
    center = frames[index]
    start, end = _context_bounds(frames, index, config)
    features: list[list[float]] = []
    anchors = [(0.0, 0.0)] * config.num_keypoints
    nearest = [math.inf] * config.num_keypoints
    leftmost = index - config.past_frames
    for neighbor in range(leftmost, leftmost + config.window_length):
        if not start <= neighbor < end:
            features.append([0.0] * (FRAME_CHANNELS + POINT_CHANNELS * config.num_keypoints))
            continue
        frame = frames[neighbor]
        sequence.validate_points(frame.observations, config.num_keypoints)
        elapsed = frame.timestamp_seconds - center.timestamp_seconds
        row = [
            1.0,
            float(frame.observations is not None),
            _signed_log(elapsed),
            _signed_log(frame.frame_index - center.frame_index),
        ]
        for slot in range(config.num_keypoints):
            point = frame.observations[slot] if frame.observations is not None else None
            coordinates = point.coordinates if point is not None else None
            confidence = point.confidence if point is not None else None
            xy = (0.0, 0.0)
            if coordinates is not None:
                xy = normalize_point(*coordinates, width=sequence.width, height=sequence.height)
                if abs(elapsed) < nearest[slot]:
                    nearest[slot] = abs(elapsed)
                    anchors[slot] = xy
            row.extend(
                (
                    *xy,
                    float(coordinates is not None),
                    confidence or 0.0,
                    float(confidence is not None),
                )
            )
            row.extend(
                float(point is not None and point.visibility == state)
                for state in VISIBILITY_CHANNELS
            )
        features.append(row)
    return _Window(
        features,
        anchors,
        [math.isfinite(distance) for distance in nearest],
        end - index - 1,
        frames[end - 1].timestamp_seconds - center.timestamp_seconds,
    )


def _checked_cancellation(cancelled: CancellationCheck | None) -> None:
    if cancelled is not None and cancelled():
        raise ReefPoseCancelledError("Temporal ReefPose operation cancelled")


def _batches(
    items: Sequence[_Item], requested_size: int, config: TemporalConfig
) -> Iterator[Sequence[_Item]]:
    size = config.effective_batch_size(requested_size)
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _batch_coordinates(model: TemporalRefiner, windows: Sequence[_Window]) -> torch.Tensor:
    device = model.input_projection.weight.device
    features = torch.tensor(
        [window.features for window in windows], dtype=torch.float32, device=device
    )
    anchors = torch.tensor(
        [window.anchors for window in windows], dtype=torch.float32, device=device
    )
    return cast(torch.Tensor, model(features, anchors))


def iter_refined(
    model: TemporalRefiner,
    sequence: TemporalSequence,
    *,
    chunk_size: int = 256,
    cancelled: CancellationCheck | None = None,
) -> Iterator[TemporalFrameResult]:
    """Refine bounded-size batches with the same source context at every boundary."""
    if type(chunk_size) is not int or not 1 <= chunk_size <= 8192:
        raise ReefPoseValidationError("Temporal inference chunk size must be 1 to 8192")
    _checked_cancellation(cancelled)
    if model.schema_hash is not None and model.schema_hash != sequence.schema_hash:
        raise ReefPoseValidationError("Temporal model and sequence anatomy schema differ")
    model.eval()
    for indices in _batches(range(len(sequence.frames)), chunk_size, model.config):
        _checked_cancellation(cancelled)
        windows = [_window(sequence, index, model.config) for index in indices]
        with torch.inference_mode():
            positions = _batch_coordinates(model, windows).clamp(-1, 1).cpu().tolist()
        for index, window, row in zip(indices, windows, positions, strict=True):
            frame = sequence.frames[index]
            points: list[TemporalPoint | None] = []
            for slot, available in enumerate(window.available):
                if not available:
                    points.append(None)
                    continue
                x, y = denormalize_point(*row[slot], width=sequence.width, height=sequence.height)
                original = frame.observations[slot] if frame.observations is not None else None
                visibility = (
                    original.visibility
                    if original is not None and original.coordinates is not None
                    else "uncertain"
                )
                points.append(TemporalPoint(x=x, y=y, visibility=visibility))
            yield TemporalFrameResult(
                frame.frame_index,
                frame.timestamp_seconds,
                tuple(points),
                window.future_frames,
                window.future_seconds,
            )


@dataclass(slots=True)
class TemporalTrainingResult:
    model: TemporalRefiner
    state: dict[str, Any]
    metrics_history: list[dict[str, float]]


def _paired_points(
    sequence: TemporalSequence, index: int, window: _Window
) -> tuple[list[tuple[float, float]], list[bool]]:
    frame = sequence.frames[index]
    points: list[tuple[float, float]] = []
    mask: list[bool] = []
    for slot, available in enumerate(window.available):
        target = frame.targets[slot] if frame.targets is not None else None
        xy = target.coordinates if available and target is not None else None
        mask.append(xy is not None)
        points.append(
            normalize_point(*xy, width=sequence.width, height=sequence.height)
            if xy is not None
            else (0.0, 0.0)
        )
    return points, mask


def _epoch(
    model: TemporalRefiner,
    samples: list[tuple[TemporalSequence, int]],
    config: TemporalTrainingConfig,
    *,
    optimizer: torch.optim.Optimizer | None,
    cancelled: CancellationCheck | None,
) -> tuple[dict[str, float], int]:
    model.train(optimizer is not None)
    device = model.input_projection.weight.device
    total_loss, total_px, points, steps = 0.0, 0.0, 0, 0
    for batch in _batches(samples, config.batch_size, model.config):
        _checked_cancellation(cancelled)
        windows = [_window(sequence, index, model.config) for sequence, index in batch]
        pairs = [
            _paired_points(sequence, index, window)
            for (sequence, index), window in zip(batch, windows, strict=True)
        ]
        count = sum(sum(mask) for _, mask in pairs)
        if count == 0:
            continue
        target = torch.tensor([row for row, _ in pairs], device=device, dtype=torch.float32)
        mask = torch.tensor([mask for _, mask in pairs], device=device, dtype=torch.bool)
        with torch.set_grad_enabled(optimizer is not None):
            predicted = _batch_coordinates(model, windows)
            if config.loss == "smooth_l1":
                loss = F.smooth_l1_loss(predicted[mask], target[mask], beta=config.smooth_l1_beta)
            else:
                loss = F.mse_loss(predicted[mask], target[mask])
            if not bool(torch.isfinite(loss)):
                raise ReefPoseValidationError("Temporal training loss is not finite")
            if optimizer is not None:
                optimizer.zero_grad(set_to_none=True)
                torch.autograd.backward(loss)
                nn.utils.clip_grad_norm_(model.parameters(), 5.0, error_if_nonfinite=True)
                optimizer.step()
                steps += 1
        scales = torch.tensor(
            [(sequence.width / 2, sequence.height / 2) for sequence, _ in batch],
            dtype=torch.float32,
            device=device,
        )
        pixel_error = ((predicted.detach() - target) * scales[:, None, :]).norm(dim=-1)
        total_px += float(pixel_error[mask].sum().item())
        total_loss += float(loss.item()) * count
        points += count
    metrics = {"supervised_points": float(points)}
    if points:
        metrics.update(loss=total_loss / points, mean_localization_error_px=total_px / points)
    return metrics, steps


def _fingerprint(sequences: Sequence[TemporalSequence], splits: Mapping[str, TemporalSplit]) -> str:
    digest = hashlib.sha256()
    options: dict[str, Any] = {"sort_keys": True, "separators": (",", ":"), "allow_nan": False}
    for sequence in sequences:
        identity = (
            sequence.recording_id,
            sequence.animal_id,
            sequence.group_key,
            splits[sequence.group_key],
            sequence.schema_hash,
            sequence.width,
            sequence.height,
            sequence.identity_revision,
            sequence.calibration_id,
            sequence.subject_id,
        )
        digest.update(json.dumps(identity, **options).encode("utf-8"))
        for frame in sequence.frames:
            digest.update(json.dumps(asdict(frame), **options).encode("utf-8"))
    return digest.hexdigest()


def _snapshot(value: Any) -> Any:
    if isinstance(value, torch.Tensor):
        return value.detach().to(device="cpu", copy=True)
    if isinstance(value, dict):
        return {key: _snapshot(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_snapshot(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_snapshot(item) for item in value)
    return value


def load_temporal_model(state: dict[str, Any], *, device: str = "cpu") -> TemporalRefiner:
    """Restore validated temporal weights. The storage layer owns artifact I/O."""
    if (
        state.get("format") != TEMPORAL_FORMAT
        or state.get("architecture") != TemporalRefiner.architecture_name
        or state.get("architecture_version") != TemporalRefiner.architecture_version
        or state.get("normalization") != NORMALIZATION
        or state.get("timing_policy") != TIMING_POLICY
    ):
        raise ReefPoseValidationError("Unsupported temporal ReefPose checkpoint")
    resolved_device = resolve_device(device)
    try:
        config = TemporalConfig(**state["model_config"])
        schema_hash = state["schema_hash"]
        if not isinstance(schema_hash, str) or not schema_hash:
            raise TypeError
        model = TemporalRefiner(config, schema_hash)
        model.to(resolved_device)
        model.load_state_dict(state["model_state"], strict=True)
        if any(not bool(torch.isfinite(parameter).all()) for parameter in model.parameters()):
            raise ReefPoseValidationError("Temporal checkpoint contains non-finite weights")
    except (KeyError, TypeError, RuntimeError, ValueError) as exc:
        if isinstance(exc, ReefPoseValidationError):
            raise
        raise ReefPoseValidationError("Temporal checkpoint contents are invalid") from exc
    model.eval()
    return model


def train_temporal(
    sequences: Sequence[TemporalSequence],
    splits: Mapping[str, TemporalSplit],
    config: TemporalConfig,
    training: TemporalTrainingConfig,
    *,
    resume: dict[str, Any] | None = None,
    on_epoch: EpochCallback | None = None,
    cancelled: CancellationCheck | None = None,
) -> TemporalTrainingResult:
    """Train exclusively on reviewed coordinates and persist restartable epoch state."""
    _checked_cancellation(cancelled)
    if not sequences:
        raise ReefPoseValidationError("Temporal training requires frozen sequences")
    validate_splits(sequences, splits)
    ordered = sorted(sequences, key=lambda sequence: (sequence.recording_id, sequence.animal_id))
    schema_hash = ordered[0].schema_hash
    samples: dict[str, list[tuple[TemporalSequence, int]]] = {"train": [], "validation": []}
    for sequence in ordered:
        _checked_cancellation(cancelled)
        if sequence.schema_hash != schema_hash:
            raise ReefPoseValidationError("Temporal training sequences require one anatomy schema")
        sequence.validate_landmarks(config.num_keypoints)
        split = splits[sequence.group_key]
        if split in samples:
            samples[split].extend(
                (sequence, index)
                for index, frame in enumerate(sequence.frames)
                if frame.targets is not None
                and any(
                    point is not None and point.coordinates is not None for point in frame.targets
                )
            )
    if not samples["train"]:
        raise ReefPoseValidationError("Temporal training split has no human-verified coordinates")
    fingerprint = _fingerprint(ordered, splits)
    training_config = asdict(training)
    device = resolve_device(training.device)
    history: list[dict[str, float]] = []
    completed_epochs = 0
    global_step = 0
    with torch.random.fork_rng(devices=[]):
        torch.default_generator.manual_seed(training.seed)
        model = TemporalRefiner(config, schema_hash)
    model.to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=training.learning_rate, weight_decay=training.weight_decay
    )
    if resume is not None:
        previous_config = resume.get("training_config")
        fixed_options = training_config.keys() - {"epochs", "device"}
        if (
            resume.get("dataset_fingerprint") != fingerprint
            or not isinstance(previous_config, dict)
            or any(previous_config.get(name) != training_config[name] for name in fixed_options)
            or resume.get("model_config") != asdict(config)
        ):
            raise ReefPoseValidationError(
                "Temporal resume requires the same data and configuration"
            )
        try:
            restored = load_temporal_model(resume, device=training.device)
            model.load_state_dict(restored.state_dict())
            optimizer.load_state_dict(resume["optimizer_state"])
            completed_epochs = resume["epoch"]
            global_step = resume["global_step"]
            history = list(resume["metrics_history"])
            if (
                type(completed_epochs) is not int
                or not 1 <= completed_epochs <= training.epochs
                or type(global_step) is not int
                or global_step < completed_epochs
                or len(history) != completed_epochs
            ):
                raise ValueError
        except (KeyError, TypeError, RuntimeError, ValueError) as exc:
            raise ReefPoseValidationError("Temporal training resume state is invalid") from exc

    state: dict[str, Any] = {}
    for epoch in range(completed_epochs + 1, training.epochs + 1):
        train_samples = samples["train"].copy()
        random.Random(training.seed + epoch).shuffle(train_samples)
        train_metrics, steps = _epoch(
            model, train_samples, training, optimizer=optimizer, cancelled=cancelled
        )
        if steps == 0:
            raise ReefPoseValidationError("Temporal training targets have no usable context")
        validation_metrics, _ = _epoch(
            model, samples["validation"], training, optimizer=None, cancelled=cancelled
        )
        global_step += steps
        metrics = {
            "epoch": float(epoch),
            **{f"train_{k}": v for k, v in train_metrics.items()},
            **{f"validation_{k}": v for k, v in validation_metrics.items()},
        }
        history.append(metrics)
        if on_epoch is not None or epoch == training.epochs:
            state = {
                "format": TEMPORAL_FORMAT,
                "architecture": TemporalRefiner.architecture_name,
                "architecture_version": TemporalRefiner.architecture_version,
                "model_config": asdict(config),
                "training_config": training_config,
                "schema_hash": schema_hash,
                "normalization": NORMALIZATION,
                "timing_policy": TIMING_POLICY,
                "dataset_fingerprint": fingerprint,
                "epoch": epoch,
                "global_step": global_step,
                "model_state": _snapshot(model.state_dict()),
                "optimizer_state": _snapshot(optimizer.state_dict()),
                "metrics_history": [item.copy() for item in history],
                "torch_version": str(torch.__version__),
                "resolved_device": str(device),
            }
            if on_epoch is not None:
                on_epoch(epoch, metrics, state)
        _checked_cancellation(cancelled)
    model.eval()
    return TemporalTrainingResult(model, state or dict(resume or {}), history)
