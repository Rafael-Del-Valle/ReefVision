"""Deterministic, dependency-free multi-animal pose identity association."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from math import hypot
from typing import Literal

ALGORITHM = "reefpose-geometric-motion-association"
ALGORITHM_VERSION = "1.0.0"
_INF = 1_000_000.0


@dataclass(frozen=True)
class Landmark:
    landmark_id: str
    x: float | None
    y: float | None
    confidence: float | None = None
    visibility: str = "visible"


@dataclass(frozen=True)
class PoseDetection:
    detection_id: str
    source_track_id: str
    frame_index: int
    bbox: tuple[float, float, float, float]
    landmarks: tuple[Landmark, ...] = ()
    confidence: float = 1.0


@dataclass(frozen=True)
class AssociationConfig:
    max_gap_frames: int = 5
    max_normalized_distance: float = 1.5
    minimum_iou: float = 0.0
    minimum_landmark_similarity: float = 0.0
    minimum_detection_confidence: float = 0.05
    acceptance_threshold: float = 0.75
    low_confidence_threshold: float = 0.6
    proximity_weight: float = 0.35
    overlap_weight: float = 0.2
    landmark_weight: float = 0.25
    motion_weight: float = 0.2
    confidence_weight: float = 0.1

    def __post_init__(self) -> None:
        if self.max_gap_frames < 0:
            raise ValueError("max_gap_frames must be non-negative")
        if self.max_normalized_distance <= 0 or self.acceptance_threshold <= 0:
            raise ValueError("Association distance and threshold must be positive")
        if not 0 <= self.minimum_detection_confidence <= 1:
            raise ValueError("minimum_detection_confidence must be between zero and one")
        weights = (
            self.proximity_weight,
            self.overlap_weight,
            self.landmark_weight,
            self.motion_weight,
            self.confidence_weight,
        )
        if any(weight < 0 for weight in weights) or sum(weights) <= 0:
            raise ValueError("Association weights must be non-negative with a positive sum")


@dataclass(frozen=True)
class IdentityAssignment:
    detection_id: str
    source_track_id: str
    frame_index: int
    identity_key: str | None
    association_confidence: float
    state: str


@dataclass(frozen=True)
class IdentitySummary:
    identity_key: str
    first_frame: int
    last_frame: int
    lifecycle_state: Literal["active", "terminated"]
    mean_association_confidence: float


@dataclass(frozen=True)
class AssociationDecision:
    detection_id: str
    frame_index: int
    candidate_identity_key: str | None
    candidate_rank: int
    selected: bool
    passed_gate: bool
    gate_reason: str | None
    total_cost: float
    acceptance_threshold: float
    association_confidence: float
    score_components: dict[str, float | None]


@dataclass(frozen=True)
class OcclusionInterval:
    identity_key: str
    start_frame: int
    end_frame: int
    recovery_confidence: float


@dataclass(frozen=True)
class AssociationResult:
    assignments: tuple[IdentityAssignment, ...]
    identities: tuple[IdentitySummary, ...]
    decisions: tuple[AssociationDecision, ...]
    occlusions: tuple[OcclusionInterval, ...]
    parameters_sha256: str
    algorithm: str = ALGORITHM
    algorithm_version: str = ALGORITHM_VERSION


@dataclass
class _Track:
    identity_key: str
    observations: list[PoseDetection]
    confidences: list[float] = field(default_factory=list)
    lifecycle_state: Literal["active", "terminated"] = "active"


@dataclass(frozen=True)
class _Candidate:
    track_index: int
    detection_index: int
    total_cost: float
    passed_gate: bool
    gate_reason: str | None
    confidence: float
    components: dict[str, float | None]


def _center(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    x, y, width, height = bbox
    return x + width / 2.0, y + height / 2.0


def _scale(*bboxes: tuple[float, float, float, float]) -> float:
    return max(1.0, sum(hypot(box[2], box[3]) for box in bboxes) / len(bboxes))


def _iou(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    left, top = max(ax, bx), max(ay, by)
    right, bottom = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    union = aw * ah + bw * bh - intersection
    return intersection / union if union > 0 else 0.0


def _valid_landmarks(detection: PoseDetection) -> dict[str, Landmark]:
    return {
        item.landmark_id: item
        for item in detection.landmarks
        if item.x is not None
        and item.y is not None
        and item.visibility == "visible"
        and (item.confidence is None or item.confidence > 0)
    }


def _landmark_cost(first: PoseDetection, second: PoseDetection) -> float | None:
    first_landmarks = _valid_landmarks(first)
    second_landmarks = _valid_landmarks(second)
    common = sorted(first_landmarks.keys() & second_landmarks.keys())
    if not common:
        return None
    first_center = _center(first.bbox)
    second_center = _center(second.bbox)
    scale = _scale(first.bbox, second.bbox)
    distances = []
    for landmark_id in common:
        left = first_landmarks[landmark_id]
        right = second_landmarks[landmark_id]
        assert left.x is not None and left.y is not None
        assert right.x is not None and right.y is not None
        distances.append(
            hypot(
                (left.x - first_center[0]) - (right.x - second_center[0]),
                (left.y - first_center[1]) - (right.y - second_center[1]),
            )
            / scale
        )
    return min(1.0, sum(distances) / len(distances))


def _predicted_center(track: _Track, frame_index: int) -> tuple[float, float]:
    latest = track.observations[-1]
    latest_center = _center(latest.bbox)
    if len(track.observations) < 2:
        return latest_center
    previous = track.observations[-2]
    previous_center = _center(previous.bbox)
    elapsed = latest.frame_index - previous.frame_index
    if elapsed <= 0:
        return latest_center
    horizon = frame_index - latest.frame_index
    return (
        latest_center[0] + (latest_center[0] - previous_center[0]) / elapsed * horizon,
        latest_center[1] + (latest_center[1] - previous_center[1]) / elapsed * horizon,
    )


def _score(track: _Track, detection: PoseDetection, config: AssociationConfig) -> _Candidate:
    latest = track.observations[-1]
    current_center = _center(detection.bbox)
    scale = _scale(latest.bbox, detection.bbox)
    proximity_cost = (
        hypot(*(current_center[index] - _center(latest.bbox)[index] for index in range(2))) / scale
    )
    predicted = _predicted_center(track, detection.frame_index)
    motion_cost = hypot(current_center[0] - predicted[0], current_center[1] - predicted[1]) / scale
    overlap = _iou(latest.bbox, detection.bbox)
    overlap_cost = 1.0 - overlap
    landmark_cost = _landmark_cost(latest, detection)
    confidence_cost = 1.0 - detection.confidence
    components: dict[str, float | None] = {
        "proximity_cost": proximity_cost,
        "overlap_cost": overlap_cost,
        "landmark_cost": landmark_cost,
        "motion_cost": motion_cost,
        "confidence_cost": confidence_cost,
    }
    weighted = [
        (proximity_cost, config.proximity_weight),
        (overlap_cost, config.overlap_weight),
        (landmark_cost, config.landmark_weight),
        (motion_cost, config.motion_weight),
        (confidence_cost, config.confidence_weight),
    ]
    available = [(value, weight) for value, weight in weighted if value is not None and weight > 0]
    total_cost = sum(value * weight for value, weight in available) / sum(
        weight for _value, weight in available
    )

    gate_reason: str | None = None
    if detection.confidence < config.minimum_detection_confidence:
        gate_reason = "detection_confidence"
    elif min(proximity_cost, motion_cost) > config.max_normalized_distance:
        gate_reason = "normalized_distance"
    elif config.minimum_iou > 0 and overlap < config.minimum_iou:
        gate_reason = "bbox_iou"
    elif (
        config.minimum_landmark_similarity > 0
        and landmark_cost is not None
        and 1.0 - landmark_cost < config.minimum_landmark_similarity
    ):
        gate_reason = "landmark_similarity"
    elif total_cost > config.acceptance_threshold:
        gate_reason = "total_cost"
    passed = gate_reason is None
    confidence = (
        max(0.0, 1.0 - total_cost / config.acceptance_threshold) * detection.confidence
        if passed
        else 0.0
    )
    return _Candidate(
        track_index=-1,
        detection_index=-1,
        total_cost=total_cost,
        passed_gate=passed,
        gate_reason=gate_reason,
        confidence=confidence,
        components=components,
    )


def minimum_cost_assignment(costs: list[list[float]]) -> list[int]:
    """Return one selected column per row using deterministic rectangular Hungarian."""

    if not costs:
        return []
    row_count = len(costs)
    column_count = len(costs[0])
    if column_count < row_count:
        raise ValueError("Hungarian matrix must have at least as many columns as rows")
    u = [0.0] * (row_count + 1)
    v = [0.0] * (column_count + 1)
    p = [0] * (column_count + 1)
    way = [0] * (column_count + 1)
    for row in range(1, row_count + 1):
        p[0] = row
        column0 = 0
        minimum = [_INF] * (column_count + 1)
        used = [False] * (column_count + 1)
        while True:
            used[column0] = True
            current_row = p[column0]
            delta = _INF
            column1 = 0
            for column in range(1, column_count + 1):
                if used[column]:
                    continue
                reduced = costs[current_row - 1][column - 1] - u[current_row] - v[column]
                if reduced < minimum[column]:
                    minimum[column] = reduced
                    way[column] = column0
                if minimum[column] < delta:
                    delta = minimum[column]
                    column1 = column
            for column in range(column_count + 1):
                if used[column]:
                    u[p[column]] += delta
                    v[column] -= delta
                else:
                    minimum[column] -= delta
            column0 = column1
            if p[column0] == 0:
                break
        while True:
            column1 = way[column0]
            p[column0] = p[column1]
            column0 = column1
            if column0 == 0:
                break
    assignment = [-1] * row_count
    for column in range(1, column_count + 1):
        if p[column] != 0:
            assignment[p[column] - 1] = column - 1
    return assignment


def _parameters_hash(config: AssociationConfig) -> str:
    payload = json.dumps(asdict(config), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def associate_pose_identities(
    detections: list[PoseDetection], config: AssociationConfig
) -> AssociationResult:
    """Associate detections without asserting unsupported long-gap re-identification."""

    ordered = sorted(detections, key=lambda item: (item.frame_index, item.detection_id))
    if any(item.frame_index < 0 for item in ordered):
        raise ValueError("frame_index must be non-negative")
    tracks: list[_Track] = []
    assignments: list[IdentityAssignment] = []
    decisions: list[AssociationDecision] = []
    occlusions: list[OcclusionInterval] = []
    next_identity = 1

    frames = sorted({item.frame_index for item in ordered})
    by_frame = {frame: [item for item in ordered if item.frame_index == frame] for frame in frames}
    for frame in frames:
        frame_detections = by_frame[frame]
        for track in tracks:
            if frame - track.observations[-1].frame_index - 1 > config.max_gap_frames:
                track.lifecycle_state = "terminated"
        active_indices = [
            index for index, track in enumerate(tracks) if track.lifecycle_state == "active"
        ]

        candidates: dict[tuple[int, int], _Candidate] = {}
        for active_row, track_index in enumerate(active_indices):
            for detection_index, detection in enumerate(frame_detections):
                raw = _score(tracks[track_index], detection, config)
                candidates[(active_row, detection_index)] = _Candidate(
                    track_index=track_index,
                    detection_index=detection_index,
                    total_cost=raw.total_cost,
                    passed_gate=raw.passed_gate,
                    gate_reason=raw.gate_reason,
                    confidence=raw.confidence,
                    components=raw.components,
                )

        selected_by_detection: dict[int, _Candidate] = {}
        if active_indices:
            real_columns = len(frame_detections)
            matrix: list[list[float]] = []
            for active_row, _track_index in enumerate(active_indices):
                row = []
                for detection_index in range(real_columns):
                    candidate = candidates[(active_row, detection_index)]
                    row.append(candidate.total_cost if candidate.passed_gate else _INF)
                row.extend(
                    config.acceptance_threshold + 1e-6 + dummy_index * 1e-9
                    for dummy_index in range(len(active_indices))
                )
                matrix.append(row)
            for active_row, selected_column in enumerate(minimum_cost_assignment(matrix)):
                if selected_column < real_columns:
                    candidate = candidates[(active_row, selected_column)]
                    if candidate.passed_gate:
                        selected_by_detection[selected_column] = candidate

        for detection_index, detection in enumerate(frame_detections):
            ranked = sorted(
                (
                    candidate
                    for (active_row, candidate_detection), candidate in candidates.items()
                    if candidate_detection == detection_index
                ),
                key=lambda item: (
                    item.total_cost,
                    tracks[item.track_index].identity_key,
                ),
            )
            selected = selected_by_detection.get(detection_index)
            for rank, candidate in enumerate(ranked, start=1):
                decisions.append(
                    AssociationDecision(
                        detection_id=detection.detection_id,
                        frame_index=frame,
                        candidate_identity_key=tracks[candidate.track_index].identity_key,
                        candidate_rank=rank,
                        selected=candidate is selected,
                        passed_gate=candidate.passed_gate,
                        gate_reason=candidate.gate_reason,
                        total_cost=candidate.total_cost,
                        acceptance_threshold=config.acceptance_threshold,
                        association_confidence=candidate.confidence,
                        score_components=candidate.components,
                    )
                )

            if selected is not None:
                track = tracks[selected.track_index]
                previous_frame = track.observations[-1].frame_index
                if frame - previous_frame > 1:
                    occlusions.append(
                        OcclusionInterval(
                            identity_key=track.identity_key,
                            start_frame=previous_frame + 1,
                            end_frame=frame - 1,
                            recovery_confidence=selected.confidence,
                        )
                    )
                track.observations.append(detection)
                track.confidences.append(selected.confidence)
                state = (
                    "matched_low_confidence"
                    if selected.confidence < config.low_confidence_threshold
                    else "matched"
                )
                assignments.append(
                    IdentityAssignment(
                        detection_id=detection.detection_id,
                        source_track_id=detection.source_track_id,
                        frame_index=frame,
                        identity_key=track.identity_key,
                        association_confidence=selected.confidence,
                        state=state,
                    )
                )
                continue

            if detection.confidence < config.minimum_detection_confidence:
                assignments.append(
                    IdentityAssignment(
                        detection_id=detection.detection_id,
                        source_track_id=detection.source_track_id,
                        frame_index=frame,
                        identity_key=None,
                        association_confidence=0.0,
                        state="rejected_low_confidence",
                    )
                )
                continue

            identity_key = f"animal-{next_identity:04d}"
            next_identity += 1
            track = _Track(
                identity_key=identity_key,
                observations=[detection],
                confidences=[detection.confidence],
            )
            tracks.append(track)
            assignments.append(
                IdentityAssignment(
                    detection_id=detection.detection_id,
                    source_track_id=detection.source_track_id,
                    frame_index=frame,
                    identity_key=identity_key,
                    association_confidence=detection.confidence,
                    state="initiated",
                )
            )
            decisions.append(
                AssociationDecision(
                    detection_id=detection.detection_id,
                    frame_index=frame,
                    candidate_identity_key=identity_key,
                    candidate_rank=len(ranked) + 1,
                    selected=True,
                    passed_gate=True,
                    gate_reason="track_initiated",
                    total_cost=0.0,
                    acceptance_threshold=config.acceptance_threshold,
                    association_confidence=detection.confidence,
                    score_components={
                        "proximity_cost": None,
                        "overlap_cost": None,
                        "landmark_cost": None,
                        "motion_cost": None,
                        "confidence_cost": 1.0 - detection.confidence,
                    },
                )
            )

    identities = tuple(
        IdentitySummary(
            identity_key=track.identity_key,
            first_frame=track.observations[0].frame_index,
            last_frame=track.observations[-1].frame_index,
            lifecycle_state=track.lifecycle_state,
            mean_association_confidence=sum(track.confidences) / len(track.confidences),
        )
        for track in tracks
    )
    return AssociationResult(
        assignments=tuple(assignments),
        identities=identities,
        decisions=tuple(decisions),
        occlusions=tuple(occlusions),
        parameters_sha256=_parameters_hash(config),
    )
