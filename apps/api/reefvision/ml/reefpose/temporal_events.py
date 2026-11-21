"""Compare anatomical movement cycles derived from the same temporal evidence."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any

from reefvision.domain.pose_biological_events import (
    BiologicalEventCandidate,
    CycleDefinition,
    EventSignalSample,
    detect_biological_events,
)
from reefvision.domain.reefpose_agreement import (
    ScoredEvent,
    event_agreement,
    measurement_agreement,
    rate,
)
from reefvision.ml.reefpose.errors import ReefPoseValidationError
from reefvision.ml.reefpose.temporal_data import TemporalFrame

_STREAMS = ("reference", "frame_only", "refined")
_TIMING_FIELDS = ("onset_error_s", "offset_error_s", "duration_error_s", "peak_error_s")


@dataclass(frozen=True, slots=True)
class AnatomicalEventConfig:
    landmark_ids: tuple[str, str]
    landmark_slots: tuple[int, int]
    definition: CycleDefinition
    onset_tolerance_seconds: float = 0.25
    offset_tolerance_seconds: float = 0.25

    def __post_init__(self) -> None:
        if len(set(self.landmark_ids)) != 2 or any(not key.strip() for key in self.landmark_ids):
            raise ReefPoseValidationError("Anatomical cycles require two distinct landmark IDs")
        if len(set(self.landmark_slots)) != 2 or min(self.landmark_slots) < 0:
            raise ReefPoseValidationError("Anatomical cycle landmark slots must be distinct")
        if self.definition.close_threshold < 0 or self.definition.minimum_confidence != 0:
            raise ReefPoseValidationError(
                "Anatomical cycles require nonnegative distances and an unfiltered confidence gate"
            )
        limits = (
            self.definition.minimum_amplitude,
            self.definition.minimum_duration_s,
            self.definition.maximum_duration_s,
            self.definition.minimum_separation_s,
            self.definition.refractory_s,
            self.definition.maximum_gap_s,
            self.onset_tolerance_seconds,
            self.offset_tolerance_seconds,
        )
        if any(value is not None and (not math.isfinite(value) or value < 0) for value in limits):
            raise ReefPoseValidationError("Anatomical cycle limits must be finite and nonnegative")


def _as_scored(event: BiologicalEventCandidate, stream: str) -> ScoredEvent:
    return ScoredEvent(
        id=f"{stream}:{event.start_frame}",
        start=event.start_time_s,
        peak=event.peak_time_s,
        end=event.end_time_s,
        amplitude=event.amplitude,
        amplitude_unit="px",
    )


def _evidence(event: BiologicalEventCandidate) -> dict[str, Any]:
    payload = asdict(event)
    payload["eligible_complete_cycle"] = payload.pop("accepted")
    # The detector's binary coordinate-support flag is not model confidence.
    del payload["confidence"]
    return payload


class AnatomicalEventComparison:
    def __init__(self, config: AnatomicalEventConfig, max_gap_seconds: float | None) -> None:
        self.config = config
        self.gap_seconds = config.definition.maximum_gap_s
        if max_gap_seconds is not None:
            self.gap_seconds = min(self.gap_seconds, max_gap_seconds)
        self.coverage: Counter[str] = Counter()
        self.sequences: list[dict[str, Any]] = []
        self._segments: list[dict[str, Any]] = []
        self._samples: list[list[EventSignalSample]] = [[], [], []]

    def observe(
        self,
        frame: TemporalFrame,
        animal_id: str,
        distances: tuple[float | None, float | None, float | None],
    ) -> None:
        self.coverage["frozen_frames"] += 1
        for stream, distance in zip(_STREAMS, distances, strict=True):
            self.coverage[f"{stream}_missing_frames"] += distance is None
        common = all(distance is not None for distance in distances)
        prior = self._samples[0][-1] if self._samples[0] else None
        if (
            frame.discontinuity
            or not common
            or (prior is not None and frame.timestamp_seconds - prior.time_s > self.gap_seconds)
        ):
            self._flush()
        if common:
            self.coverage["common_frames"] += 1
            for samples, distance in zip(self._samples, distances, strict=True):
                samples.append(
                    EventSignalSample(
                        frame.frame_index, frame.timestamp_seconds, distance, 1.0, True, animal_id
                    )
                )

    def _flush(self) -> None:
        if not self._samples[0]:
            return
        first, last = self._samples[0][0], self._samples[0][-1]
        candidates = {
            stream: detect_biological_events(samples, self.config.definition).events
            for stream, samples in zip(_STREAMS, self._samples, strict=True)
        }
        complete = {
            stream: [_as_scored(event, stream) for event in events if event.accepted]
            for stream, events in candidates.items()
        }
        self._segments.append(
            {
                "start_frame": first.frame_index,
                "end_frame": last.frame_index,
                "evaluated_seconds": last.time_s - first.time_s,
                "candidates": {
                    stream: [_evidence(event) for event in events]
                    for stream, events in candidates.items()
                },
                "matches": {
                    stream: event_agreement(
                        complete["reference"],
                        complete[stream],
                        self.config.onset_tolerance_seconds,
                        self.config.offset_tolerance_seconds,
                    )
                    for stream in ("frame_only", "refined")
                },
            }
        )
        self._samples = [[], [], []]

    def finish_sequence(self, recording_id: str, animal_id: str) -> None:
        self._flush()
        self.sequences.append(
            {"recording_id": recording_id, "animal_id": animal_id, "segments": self._segments}
        )
        self._segments = []

    def summary(self) -> dict[str, Any]:
        segments = [segment for sequence in self.sequences for segment in sequence["segments"]]
        duration = float(sum(segment["evaluated_seconds"] for segment in segments))
        return {
            "derivation": {
                "method": "reefpose-phase5-anatomical-distance-hysteresis",
                "landmark_ids": list(self.config.landmark_ids),
                "distance_units": "source_pixels",
                "reference": "phase5_detector_on_human_reviewed_landmark_distance",
                "support_policy": "common_landmark_pairs_without_missing_frames_or_discontinuities",
                "confidence_policy": "coordinate_support_without_a_model_confidence_threshold",
                "phase5_parameters": asdict(self.config.definition),
                "effective_maximum_gap_seconds": self.gap_seconds,
                "onset_tolerance_seconds": self.config.onset_tolerance_seconds,
                "offset_tolerance_seconds": self.config.offset_tolerance_seconds,
            },
            "support": {
                "frozen_frames": self.coverage["frozen_frames"],
                "common_frames": self.coverage["common_frames"],
                **{
                    f"{stream}_missing_frames": self.coverage[f"{stream}_missing_frames"]
                    for stream in _STREAMS
                },
                "common_support_segments": len(segments),
                "evaluated_seconds": duration,
            },
            "reference": _candidate_summary(segments, "reference"),
            "frame_only": _compared_summary(segments, "frame_only", duration),
            "refined": _compared_summary(segments, "refined", duration),
            "per_sequence": self.sequences,
        }


def _candidate_summary(segments: list[dict[str, Any]], stream: str) -> dict[str, int]:
    candidates = [row for segment in segments for row in segment["candidates"][stream]]
    return {
        "complete_events": sum(row["eligible_complete_cycle"] for row in candidates),
        "partial_candidates": sum(row["cycle_state"] != "complete" for row in candidates),
        "rejected_complete_candidates": sum(
            row["cycle_state"] == "complete" and not row["eligible_complete_cycle"]
            for row in candidates
        ),
    }


def _compared_summary(
    segments: list[dict[str, Any]], stream: str, evaluated_seconds: float
) -> dict[str, Any]:
    comparisons = [segment["matches"][stream] for segment in segments]
    matches = [match for comparison in comparisons for match in comparison["matches"]]
    tp, fp, fn = (sum(comparison[key] for comparison in comparisons) for key in ("tp", "fp", "fn"))
    timing = {
        key: measurement_agreement([(0.0, match[key]) for match in matches])
        for key in _TIMING_FIELDS
    }
    return {
        **_candidate_summary(segments, stream),
        "count_error": fp - fn if evaluated_seconds > 0 else None,
        "matched_events": tp,
        "missed_events": fn,
        "extra_events": fp,
        "precision": rate(tp, tp + fp),
        "recall": rate(tp, tp + fn),
        "timing_errors": {
            key: {stat: payload[stat] for stat in ("n", "bias", "mae", "rmse")}
            for key, payload in timing.items()
        },
    }
