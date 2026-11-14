"""Deterministic species-independent anatomical time-series calculations."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from hashlib import sha256
from itertools import pairwise
from statistics import fmean
from typing import Any, Literal

MeasurementKind = Literal[
    "distance",
    "angle",
    "displacement",
    "velocity",
    "direction",
    "angular_velocity",
    "curvature",
    "body_axis_orientation",
    "relative_movement",
    "extension",
]


@dataclass(frozen=True)
class AnatomicalLandmark:
    landmark_id: str
    x: float | None
    y: float | None
    confidence: float | None = None
    visibility: str = "visible"


@dataclass(frozen=True)
class AnatomicalObservation:
    observation_id: str
    revision: int
    animal_identity_id: str
    frame_index: int
    time_s: float
    coordinate_space: str
    association_confidence: float | None
    landmarks: tuple[AnatomicalLandmark, ...]


@dataclass(frozen=True)
class MeasurementCalibration:
    pixels_per_unit: float
    unit: str

    def __post_init__(self) -> None:
        if not math.isfinite(self.pixels_per_unit) or self.pixels_per_unit <= 0:
            raise ValueError("pixels_per_unit must be positive and finite")


@dataclass(frozen=True)
class MeasurementDefinition:
    definition_id: str
    kind: MeasurementKind
    landmark_ids: tuple[str, ...]
    options: dict[str, Any] | None = None


@dataclass(frozen=True)
class MeasurementSampleResult:
    frame_index: int
    time_s: float
    pixel_value: float | None
    physical_value: float | None
    confidence: float | None
    valid: bool
    quality_flags: tuple[str, ...]
    source_observation_ids: tuple[str, ...]
    source_observation_revisions: tuple[int, ...]


@dataclass(frozen=True)
class MeasurementSeriesResult:
    definition_id: str
    measurement_kind: str
    identity_id: str
    formula_version: str
    pixel_unit: str
    physical_unit: str | None
    samples: tuple[MeasurementSampleResult, ...]
    summary: dict[str, float | int | None]
    result_sha256: str


def _hash(value: Any) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _point_map(
    observation: AnatomicalObservation, ids: tuple[str, ...]
) -> tuple[list[tuple[float, float]], float | None, list[str]]:
    lookup = {p.landmark_id: p for p in observation.landmarks}
    points: list[tuple[float, float]] = []
    confidences = (
        [observation.association_confidence]
        if observation.association_confidence is not None
        else []
    )
    flags: list[str] = []
    for landmark_id in ids:
        point = lookup.get(landmark_id)
        if (
            point is None
            or point.visibility not in {"visible", "occluded"}
            or point.x is None
            or point.y is None
        ):
            flags.append("missing_landmark")
            continue
        if not math.isfinite(point.x) or not math.isfinite(point.y):
            flags.append("nonfinite_landmark")
            continue
        points.append((point.x, point.y))
        if point.confidence is not None:
            confidences.append(point.confidence)
    return points, min(confidences) if confidences else None, flags


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _orientation(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))


def _angle(
    a: tuple[float, float], vertex: tuple[float, float], c: tuple[float, float]
) -> float | None:
    u, v = (a[0] - vertex[0], a[1] - vertex[1]), (c[0] - vertex[0], c[1] - vertex[1])
    denom = math.hypot(*u) * math.hypot(*v)
    if denom == 0:
        return None
    return math.degrees(math.acos(max(-1.0, min(1.0, (u[0] * v[0] + u[1] * v[1]) / denom))))


def _unwrap_delta(current: float, previous: float) -> float:
    return (current - previous + 180) % 360 - 180


def calculate_measurement_series(
    observations: list[AnatomicalObservation] | tuple[AnatomicalObservation, ...],
    definition: MeasurementDefinition,
    calibration: MeasurementCalibration | None = None,
    *,
    identity_id: str | None = None,
    maximum_gap_s: float | None = None,
) -> MeasurementSeriesResult:
    selected = [
        o for o in observations if identity_id is None or o.animal_identity_id == identity_id
    ]
    if not selected:
        raise ValueError("No observations for the selected identity")
    identity = identity_id or selected[0].animal_identity_id
    selected = sorted(
        (o for o in selected if o.animal_identity_id == identity),
        key=lambda o: (o.time_s, o.frame_index),
    )
    if any(o.coordinate_space != "source_pixels" for o in selected):
        raise ValueError("Measurements require source_pixels coordinates")

    samples: list[MeasurementSampleResult] = []
    previous_points: list[tuple[float, float]] | None = None
    previous_time: float | None = None
    previous_scalar: float | None = None
    for observation in selected:
        points, confidence, flags = _point_map(observation, definition.landmark_ids)
        required = {
            "distance": 2,
            "angle": 3,
            "body_axis_orientation": 2,
            "angular_velocity": 2,
            "curvature": 3,
            "extension": 2,
            "relative_movement": 2,
        }.get(definition.kind, 1)
        value: float | None = None
        configured_landmarks_present = len(points) == len(definition.landmark_ids)
        if len(points) < required or not configured_landmarks_present:
            flags.append("missing_landmark")
        else:
            dt = observation.time_s - previous_time if previous_time is not None else None
            gap_invalid = dt is not None and maximum_gap_s is not None and dt > maximum_gap_s
            if definition.kind == "distance":
                value = _distance(points[0], points[1])
            elif definition.kind == "angle":
                value = _angle(points[0], points[1], points[2])
            elif definition.kind == "body_axis_orientation":
                value = _orientation(points[0], points[1])
            elif definition.kind == "curvature":
                arc_length = sum(_distance(a, b) for a, b in pairwise(points))
                interior_angles = [
                    _angle(points[index - 1], points[index], points[index + 1])
                    for index in range(1, len(points) - 1)
                ]
                value = (
                    None
                    if arc_length == 0 or any(angle is None for angle in interior_angles)
                    else sum(
                        math.radians(180 - angle) for angle in interior_angles if angle is not None
                    )
                    / arc_length
                )
            elif definition.kind == "extension":
                value = _distance(points[0], points[-1])
            elif definition.kind == "displacement":
                if previous_points is None:
                    flags.append("no_previous_sample")
                elif dt is None or dt <= 0:
                    flags.append("nonpositive_time_delta")
                elif gap_invalid:
                    flags.append("gap_exceeds_maximum")
                else:
                    value = _distance(previous_points[0], points[0])
            elif definition.kind == "relative_movement":
                scalar = _distance(points[0], points[1])
                value = 0.0 if previous_scalar is None else scalar - previous_scalar
                previous_scalar = scalar
            elif definition.kind in {"velocity", "direction"}:
                if previous_points is None:
                    flags.append("no_previous_sample")
                elif dt is None or dt <= 0:
                    flags.append("nonpositive_time_delta")
                elif gap_invalid:
                    flags.append("gap_exceeds_maximum")
                elif definition.kind == "velocity":
                    value = _distance(previous_points[0], points[0]) / dt
                else:
                    value = _orientation(previous_points[0], points[0])
            elif definition.kind == "angular_velocity":
                current = _orientation(points[0], points[1])
                if previous_scalar is None:
                    flags.append("no_previous_sample")
                elif dt is None or dt <= 0:
                    flags.append("nonpositive_time_delta")
                elif gap_invalid:
                    flags.append("gap_exceeds_maximum")
                else:
                    value = _unwrap_delta(current, previous_scalar) / dt
                previous_scalar = current
            if value is None and not flags:
                flags.append("degenerate_geometry")
        physical: float | None = None
        if value is not None and calibration:
            if definition.kind in {
                "distance",
                "displacement",
                "velocity",
                "relative_movement",
                "extension",
            }:
                physical = value / calibration.pixels_per_unit
            elif definition.kind == "curvature":
                physical = value * calibration.pixels_per_unit
        samples.append(
            MeasurementSampleResult(
                observation.frame_index,
                observation.time_s,
                value,
                physical,
                confidence,
                value is not None,
                tuple(sorted(set(flags))),
                (observation.observation_id,),
                (observation.revision,),
            )
        )
        if len(points) >= required and configured_landmarks_present:
            previous_points = points
            previous_time = observation.time_s

    valid = [s.pixel_value for s in samples if s.valid and s.pixel_value is not None]
    summary: dict[str, float | int | None] = {
        "sample_count": len(samples),
        "valid_count": len(valid),
        "minimum": min(valid) if valid else None,
        "maximum": max(valid) if valid else None,
        "mean": fmean(valid) if valid else None,
    }
    payload = {
        "definition": asdict(definition),
        "identity_id": identity,
        "samples": [asdict(s) for s in samples],
        "summary": summary,
    }
    pixel_units = {
        "distance": "pixels",
        "angle": "degrees",
        "displacement": "pixels",
        "velocity": "pixels/second",
        "direction": "degrees",
        "angular_velocity": "degrees/second",
        "curvature": "radians/pixel",
        "body_axis_orientation": "degrees",
        "relative_movement": "pixels",
        "extension": "pixels",
    }
    physical_unit: str | None = None
    if calibration:
        if definition.kind in {"distance", "displacement", "relative_movement", "extension"}:
            physical_unit = calibration.unit
        elif definition.kind == "velocity":
            physical_unit = f"{calibration.unit}/second"
        elif definition.kind == "curvature":
            physical_unit = f"radians/{calibration.unit}"
    return MeasurementSeriesResult(
        definition.definition_id,
        definition.kind,
        identity,
        "reefpose.measurement.v1",
        pixel_units[definition.kind],
        physical_unit,
        tuple(samples),
        summary,
        _hash(payload),
    )
