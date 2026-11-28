"""Source-pixel temporal ReefPose evidence and sequence boundaries."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Literal

from reefvision.ml.reefpose.errors import ReefPoseValidationError
from reefvision.ml.reefpose.schema import VISIBILITY_STATES

ContextMode = Literal["causal", "centered"]
TemporalSplit = Literal["train", "validation", "test"]


@dataclass(frozen=True, slots=True)
class TemporalPoint:
    x: float | None = None
    y: float | None = None
    confidence: float | None = None
    visibility: str = "absent"

    def __post_init__(self) -> None:
        if self.visibility not in VISIBILITY_STATES:
            raise ReefPoseValidationError("Unknown temporal landmark visibility")
        if (self.x is None) != (self.y is None) or any(
            value is not None and not math.isfinite(value) for value in (self.x, self.y)
        ):
            raise ReefPoseValidationError("Temporal landmarks require finite coordinate pairs")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ReefPoseValidationError("Temporal landmark confidence must be between 0 and 1")

    @property
    def coordinates(self) -> tuple[float, float] | None:
        if self.x is None or self.y is None or self.visibility in {"absent", "out_of_frame"}:
            return None
        return self.x, self.y


@dataclass(frozen=True, slots=True)
class TemporalFrame:
    frame_index: int
    timestamp_seconds: float
    observations: tuple[TemporalPoint, ...] | None
    # Callers must supply only human-verified coordinates as targets. A missing
    # slot is unsupervised, even when the frame model predicts a point there.
    targets: tuple[TemporalPoint | None, ...] | None = None
    discontinuity: bool = False

    def __post_init__(self) -> None:
        if type(self.frame_index) is not int or self.frame_index < 0:
            raise ReefPoseValidationError("Temporal frame indices must be nonnegative integers")
        if not math.isfinite(self.timestamp_seconds) or self.timestamp_seconds < 0:
            raise ReefPoseValidationError("Temporal frames require finite nonnegative timestamps")
        if self.observations is not None:
            object.__setattr__(self, "observations", tuple(self.observations))
        if self.targets is not None:
            object.__setattr__(self, "targets", tuple(self.targets))


@dataclass(frozen=True, slots=True)
class TemporalSequence:
    recording_id: str
    animal_id: str
    group_key: str
    schema_hash: str
    width: int
    height: int
    frames: tuple[TemporalFrame, ...]
    identity_revision: str | None = None
    calibration_id: str | None = None
    subject_id: str | None = None

    def __post_init__(self) -> None:
        if any(not key.strip() for key in (self.recording_id, self.animal_id, self.group_key)):
            raise ReefPoseValidationError(
                "Temporal sequence recording, animal and group are required"
            )
        if not self.schema_hash.strip() or min(self.width, self.height) <= 0:
            raise ReefPoseValidationError(
                "Temporal sequence schema and image dimensions are required"
            )
        object.__setattr__(self, "frames", tuple(self.frames))
        if not self.frames:
            raise ReefPoseValidationError("Temporal sequence requires at least one frame")
        for previous, frame in pairwise(self.frames):
            if frame.frame_index <= previous.frame_index:
                raise ReefPoseValidationError(
                    "Temporal frame indices must increase within a sequence"
                )
            if frame.timestamp_seconds <= previous.timestamp_seconds:
                raise ReefPoseValidationError("Temporal timestamps must increase within a sequence")

    def validate_landmarks(self, count: int) -> None:
        for frame in self.frames:
            self.validate_points(frame.observations, count)
            self.validate_points(frame.targets, count)

    def validate_points(self, points: tuple[TemporalPoint | None, ...] | None, count: int) -> None:
        if points is None:
            return
        if len(points) != count:
            raise ReefPoseValidationError("Temporal landmarks do not match the anatomy schema")
        for point in points:
            coordinates = point.coordinates if point is not None else None
            if coordinates is not None:
                x, y = coordinates
                if not (0 <= x <= self.width and 0 <= y <= self.height):
                    raise ReefPoseValidationError("Temporal landmarks lie outside source pixels")


@dataclass(frozen=True, slots=True)
class TemporalFrameResult:
    frame_index: int
    timestamp_seconds: float
    points: tuple[TemporalPoint | None, ...]
    future_frames: int
    future_seconds: float


def normalize_point(x: float, y: float, *, width: int, height: int) -> tuple[float, float]:
    """Map source-image coordinates to [-1, 1] independently along each axis."""
    return 2 * x / width - 1, 2 * y / height - 1


def denormalize_point(x: float, y: float, *, width: int, height: int) -> tuple[float, float]:
    return (x + 1) * width / 2, (y + 1) * height / 2


def validate_max_gap(max_gap_seconds: float | None) -> None:
    if max_gap_seconds is not None and (not math.isfinite(max_gap_seconds) or max_gap_seconds <= 0):
        raise ReefPoseValidationError("Temporal maximum gap must be a positive number of seconds")


def starts_segment(
    previous: TemporalFrame, frame: TemporalFrame, max_gap_seconds: float | None
) -> bool:
    return frame.discontinuity or (
        max_gap_seconds is not None
        and frame.timestamp_seconds - previous.timestamp_seconds > max_gap_seconds
    )


def validate_splits(
    sequences: Sequence[TemporalSequence], splits: Mapping[str, TemporalSplit]
) -> None:
    group_keys = {sequence.group_key for sequence in sequences}
    if set(splits) != group_keys or not set(splits.values()) <= {"train", "validation", "test"}:
        raise ReefPoseValidationError("Assign every temporal group to one explicit split")
    recording_groups: dict[str, str] = {}
    subject_groups: dict[str, str] = {}
    identities: set[tuple[str, str]] = set()
    for sequence in sequences:
        identity = sequence.recording_id, sequence.animal_id
        if identity in identities:
            raise ReefPoseValidationError("Temporal recording and animal sequences must be unique")
        identities.add(identity)
        group = sequence.group_key
        if recording_groups.setdefault(sequence.recording_id, group) != group:
            raise ReefPoseValidationError("One recording cannot cross temporal split groups")
        if (
            sequence.subject_id is not None
            and subject_groups.setdefault(sequence.subject_id, group) != group
        ):
            raise ReefPoseValidationError("One reviewed subject cannot cross temporal split groups")
