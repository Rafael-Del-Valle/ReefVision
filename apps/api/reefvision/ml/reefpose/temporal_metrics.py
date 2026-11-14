"""Paired source-pixel evaluation of frozen frame and temporal pose predictions."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from random import Random
from typing import Any

from reefvision.ml.reefpose.errors import ReefPoseValidationError
from reefvision.ml.reefpose.temporal_data import (
    TemporalFrameResult,
    TemporalPoint,
    TemporalSequence,
    TemporalSplit,
    starts_segment,
    validate_max_gap,
    validate_splits,
)

_XY = tuple[float, float]
_Interval = tuple[float, float]
_Triplet = tuple[_XY | None, _XY | None, _XY | None]


@dataclass(slots=True)
class _Mean:
    count: int = 0
    total: float = 0.0

    def add(self, value: float) -> None:
        self.count += 1
        self.total += value

    @property
    def value(self) -> float | None:
        return self.total / self.count if self.count else None


@dataclass(slots=True)
class _Coordinates:
    referenced: int = 0
    reviewed_without_coordinates: int = 0
    outputs_without_reference_coordinates: int = 0
    error: _Mean = field(default_factory=_Mean)
    squared_error: _Mean = field(default_factory=_Mean)

    def add(self, target: TemporalPoint, output: _XY | None) -> float | None:
        reference = target.coordinates
        if reference is None:
            self.reviewed_without_coordinates += 1
            self.outputs_without_reference_coordinates += output is not None
            return None
        self.referenced += 1
        if output is None:
            return None
        error = math.dist(output, reference)
        self.error.add(error)
        self.squared_error.add(error**2)
        return error

    def summary(self) -> dict[str, int | float | None]:
        mean_square = self.squared_error.value
        return {
            "reference_coordinates": self.referenced,
            "scored_coordinates": self.error.count,
            "missing_coordinates": self.referenced - self.error.count,
            "reviewed_without_coordinates": self.reviewed_without_coordinates,
            "outputs_without_reference_coordinates": self.outputs_without_reference_coordinates,
            "mean_error_px": self.error.value,
            "rmse_px": math.sqrt(mean_square) if mean_square is not None else None,
        }


@dataclass(slots=True)
class _Method:
    total: _Coordinates = field(default_factory=_Coordinates)
    by_visibility: dict[str, _Coordinates] = field(default_factory=dict)

    def add(self, target: TemporalPoint, output: _XY | None) -> float | None:
        self.by_visibility.setdefault(target.visibility, _Coordinates()).add(target, output)
        return self.total.add(target, output)

    def summary(self) -> dict[str, Any]:
        return {
            **self.total.summary(),
            "by_visibility": {
                name: scores.summary() for name, scores in sorted(self.by_visibility.items())
            },
        }


@dataclass(slots=True)
class _PairedErrors:
    original: _Mean = field(default_factory=_Mean)
    refined: _Mean = field(default_factory=_Mean)
    groups: dict[str, _Mean] = field(default_factory=dict)

    def add(self, original: float, refined: float, group: str) -> None:
        self.original.add(original)
        self.refined.add(refined)
        self.groups.setdefault(group, _Mean()).add(refined - original)

    def summary(self, bootstrap_samples: int, seed: int) -> dict[str, Any]:
        original, refined = self.original.value, self.refined.value
        return {
            "count": self.original.count,
            "groups": len(self.groups),
            "frame_only_mean_error_px": original,
            "refined_mean_error_px": refined,
            "mean_delta_px": refined - original
            if refined is not None and original is not None
            else None,
            "cluster_interval_95_px": _cluster_interval(self.groups, bootstrap_samples, seed),
        }


def _cluster_interval(groups: dict[str, _Mean], samples: int, seed: int) -> list[float] | None:
    if len(groups) < 5 or samples == 0:
        return None
    clusters = [groups[key] for key in sorted(groups)]
    random = Random(seed)
    deltas = []
    for _ in range(samples):
        selected = random.choices(clusters, k=len(clusters))
        deltas.append(sum(item.total for item in selected) / sum(item.count for item in selected))
    deltas.sort()
    return [deltas[int((len(deltas) - 1) * p)] for p in (0.025, 0.975)]


@dataclass(slots=True)
class _Speed:
    mean: _Mean = field(default_factory=_Mean)
    bias: _Mean = field(default_factory=_Mean)
    absolute_error: _Mean = field(default_factory=_Mean)

    def add(self, reference: float, output: float) -> None:
        self.mean.add(output)
        self.bias.add(output - reference)
        self.absolute_error.add(abs(output - reference))

    def summary(self) -> dict[str, float | None]:
        return {
            "mean_speed_px_per_second": self.mean.value,
            "mean_speed_bias_px_per_second": self.bias.value,
            "mae_speed_px_per_second": self.absolute_error.value,
        }


@dataclass(slots=True)
class _Trajectory:
    reference: _Mean = field(default_factory=_Mean)
    frame_only: _Speed = field(default_factory=_Speed)
    refined: _Speed = field(default_factory=_Speed)

    def add(self, reference: float, frame_only: float, refined: float) -> None:
        self.reference.add(reference)
        self.frame_only.add(reference, frame_only)
        self.refined.add(reference, refined)

    def summary(self) -> dict[str, Any]:
        return {
            "count": self.reference.count,
            "reference_mean_speed_px_per_second": self.reference.value,
            "frame_only": self.frame_only.summary(),
            "refined": self.refined.summary(),
        }


@dataclass(slots=True)
class _EventScore:
    reference: int = 0
    predicted: int = 0
    onset_error: _Mean = field(default_factory=_Mean)
    offset_error: _Mean = field(default_factory=_Mean)
    absolute_onset_error: _Mean = field(default_factory=_Mean)
    absolute_offset_error: _Mean = field(default_factory=_Mean)

    def add(self, reference: list[_Interval], predicted: list[_Interval]) -> None:
        self.reference += len(reference)
        self.predicted += len(predicted)
        known, estimate = 0, 0
        while known < len(reference) and estimate < len(predicted):
            ref_start, ref_end = reference[known]
            out_start, out_end = predicted[estimate]
            if out_end <= ref_start:
                estimate += 1
            elif ref_end <= out_start:
                known += 1
            else:
                self.onset_error.add(out_start - ref_start)
                self.offset_error.add(out_end - ref_end)
                self.absolute_onset_error.add(abs(out_start - ref_start))
                self.absolute_offset_error.add(abs(out_end - ref_end))
                known += 1
                estimate += 1

    def summary(self) -> dict[str, int | float | None]:
        return {
            "predicted_events": self.predicted,
            "count_error": self.predicted - self.reference,
            "matched_events": self.onset_error.count,
            "missed_events": self.reference - self.onset_error.count,
            "extra_events": self.predicted - self.onset_error.count,
            "mean_onset_error_seconds": self.onset_error.value,
            "mean_offset_error_seconds": self.offset_error.value,
            "mae_onset_seconds": self.absolute_onset_error.value,
            "mae_offset_seconds": self.absolute_offset_error.value,
        }


def _append_interval(events: list[_Interval], start: float, end: float) -> None:
    if events and events[-1][1] == start:
        events[-1] = events[-1][0], end
    else:
        events.append((start, end))


def _landmark_count(sequence: TemporalSequence) -> int:
    for frame in sequence.frames:
        if frame.targets is not None:
            return len(frame.targets)
        if frame.observations is not None:
            return len(frame.observations)
    return 0


def _xy(point: TemporalPoint | None) -> _XY | None:
    return point.coordinates if point is not None else None


def _edge_distance(points: Sequence[_Triplet], slots: tuple[int, int], method: int) -> float | None:
    first, last = points[slots[0]][method], points[slots[1]][method]
    return math.dist(first, last) if first is not None and last is not None else None


def evaluate_temporal_predictions(
    sequences: Sequence[TemporalSequence],
    refined: Mapping[tuple[str, str], Iterable[TemporalFrameResult]],
    *,
    movement_threshold_px_per_second: float = 20.0,
    bootstrap_samples: int = 1000,
    seed: int = 1337,
    max_gap_seconds: float | None = None,
    skeleton_edges: Sequence[tuple[int, int]] = (),
) -> dict[str, Any]:
    """Compare the same human references with paired coverage and declared-group resampling."""
    if not math.isfinite(movement_threshold_px_per_second) or movement_threshold_px_per_second <= 0:
        raise ReefPoseValidationError("Temporal movement threshold must be positive")
    if type(bootstrap_samples) is not int or not 0 <= bootstrap_samples <= 10_000:
        raise ReefPoseValidationError("Temporal bootstrap samples must be 0 to 10,000")
    validate_max_gap(max_gap_seconds)
    splits: dict[str, TemporalSplit] = {sequence.group_key: "test" for sequence in sequences}
    validate_splits(sequences, splits)
    identities = {(sequence.recording_id, sequence.animal_id) for sequence in sequences}
    if not set(refined) <= identities:
        raise ReefPoseValidationError("Refined output includes an unknown temporal sequence")

    original, output = _Method(), _Method()
    paired, anatomy = _PairedErrors(), _PairedErrors()
    trajectory = {name: _Trajectory() for name in ("stationary", "intermediate", "rapid")}
    frame_events, refined_events = _EventScore(), _EventScore()
    future_seconds, max_future_seconds, max_future_frames = _Mean(), 0.0, 0
    frames, missing_frame_observations, missing_refined_frames, recovered = 0, 0, 0, 0
    threshold = movement_threshold_px_per_second

    for sequence in sequences:
        key = sequence.recording_id, sequence.animal_id
        count = _landmark_count(sequence)
        sequence.validate_landmarks(count)
        if any(not (0 <= a < count and 0 <= b < count and a != b) for a, b in skeleton_edges):
            raise ReefPoseValidationError("Temporal skeleton edge references an invalid landmark")
        results = iter(refined.get(key, ()))
        prediction = next(results, None)
        previous_frame = None
        previous_points: list[_Triplet] | None = None
        events: list[tuple[list[_Interval], list[_Interval], list[_Interval]]] = [
            ([], [], []) for _ in range(count)
        ]

        for frame in sequence.frames:
            frames += 1
            missing_frame_observations += frame.observations is None
            predicted_points: tuple[TemporalPoint | None, ...] | None = None
            if prediction is not None and prediction.frame_index <= frame.frame_index:
                if (
                    prediction.frame_index != frame.frame_index
                    or prediction.timestamp_seconds != frame.timestamp_seconds
                    or len(prediction.points) != count
                ):
                    raise ReefPoseValidationError(
                        "Refined output does not match frozen frame identity"
                    )
                predicted_points = prediction.points
                future_seconds.add(prediction.future_seconds)
                max_future_seconds = max(max_future_seconds, prediction.future_seconds)
                max_future_frames = max(max_future_frames, prediction.future_frames)
                prediction = next(results, None)
            else:
                missing_refined_frames += 1

            coordinates: list[_Triplet] = []
            for slot in range(count):
                target = frame.targets[slot] if frame.targets is not None else None
                observed = _xy(frame.observations[slot]) if frame.observations is not None else None
                estimate = _xy(predicted_points[slot]) if predicted_points is not None else None
                coordinates.append((_xy(target), observed, estimate))
                if target is not None:
                    frame_error = original.add(target, observed)
                    refined_error = output.add(target, estimate)
                    if frame_error is not None and refined_error is not None:
                        paired.add(frame_error, refined_error, sequence.group_key)
                    recovered += (
                        target.coordinates is not None and observed is None and estimate is not None
                    )

            for edge in skeleton_edges:
                target_distance = _edge_distance(coordinates, edge, 0)
                frame_distance = _edge_distance(coordinates, edge, 1)
                refined_distance = _edge_distance(coordinates, edge, 2)
                if (
                    target_distance is not None
                    and frame_distance is not None
                    and refined_distance is not None
                ):
                    anatomy.add(
                        abs(frame_distance - target_distance),
                        abs(refined_distance - target_distance),
                        sequence.group_key,
                    )

            if (
                previous_points is not None
                and previous_frame is not None
                and not starts_segment(previous_frame, frame, max_gap_seconds)
            ):
                start, end = previous_frame.timestamp_seconds, frame.timestamp_seconds
                for prior, current, event_series in zip(
                    previous_points, coordinates, events, strict=True
                ):
                    speeds = [
                        math.dist(a, b) / (end - start)
                        for a, b in zip(prior, current, strict=True)
                        if a is not None and b is not None
                    ]
                    if len(speeds) != 3:
                        continue
                    reference_speed, frame_speed, refined_speed = speeds
                    if reference_speed >= threshold:
                        stratum = "rapid"
                    elif reference_speed <= threshold / 10:
                        stratum = "stationary"
                    else:
                        stratum = "intermediate"
                    trajectory[stratum].add(reference_speed, frame_speed, refined_speed)
                    for speed, event_list in zip(speeds, event_series, strict=True):
                        if speed >= threshold:
                            _append_interval(event_list, start, end)
            previous_frame, previous_points = frame, coordinates

        if prediction is not None:
            raise ReefPoseValidationError(
                "Refined output includes frames outside the frozen sequence"
            )
        for reference_intervals, frame_intervals, refined_intervals in events:
            frame_events.add(reference_intervals, frame_intervals)
            refined_events.add(reference_intervals, refined_intervals)

    return {
        "counts": {
            "recordings": len({sequence.recording_id for sequence in sequences}),
            "sequences": len(sequences),
            "groups": len(splits),
            "frames": frames,
            "frames_missing_observations": missing_frame_observations,
            "frames_missing_refinement": missing_refined_frames,
        },
        "landmarks": {
            "frame_only": original.summary(),
            "refined": output.summary(),
            "paired": paired.summary(bootstrap_samples, seed),
            "recovered_reference_coordinates": recovered,
        },
        "anatomical": {
            "metric": "source_pixel_distance_between_anatomical_skeleton_endpoints",
            "schema_edges": len(skeleton_edges),
            "paired": anatomy.summary(bootstrap_samples, seed),
        },
        "trajectory": {
            "common_support_intervals": sum(item.reference.count for item in trajectory.values()),
            "stationary_threshold_px_per_second": threshold / 10,
            "rapid_threshold_px_per_second": threshold,
            "max_gap_seconds": max_gap_seconds,
            **{name: item.summary() for name, item in trajectory.items()},
        },
        "movement": {
            "method": "landmark_speed_threshold_proxy",
            "support": "adjacent_intervals_with_all_three_landmark_positions",
            "threshold_px_per_second": threshold,
            "reference_events": frame_events.reference,
            "frame_only": frame_events.summary(),
            "refined": refined_events.summary(),
        },
        "context": {
            "max_future_frames": max_future_frames,
            "max_future_seconds": max_future_seconds,
            "mean_future_seconds": future_seconds.value,
        },
        "uncertainty": {
            "unit": "declared_sequence_group",
            "interval_method": "paired_cluster_percentile_bootstrap",
            "minimum_groups": 5,
            "bootstrap_samples": bootstrap_samples,
            "seed": seed,
        },
    }
