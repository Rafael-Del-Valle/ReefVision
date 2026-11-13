"""Deterministic hysteresis-based biological movement event detection."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json
import math
from statistics import fmean, median
from typing import Literal


@dataclass(frozen=True)
class EventSignalSample:
    frame_index: int
    time_s: float
    value: float | None
    confidence: float | None
    valid: bool
    animal_identity_id: str


@dataclass(frozen=True)
class CycleDefinition:
    open_threshold: float
    close_threshold: float
    minimum_amplitude: float = 0
    minimum_duration_s: float = 0
    maximum_duration_s: float | None = None
    minimum_separation_s: float = 0
    refractory_s: float = 0
    minimum_confidence: float = 0
    maximum_gap_s: float = .25
    smoothing: Literal["none", "mean", "median"] = "none"
    smoothing_window: int = 1

    def __post_init__(self) -> None:
        if not all(math.isfinite(v) for v in (self.open_threshold, self.close_threshold)) or self.open_threshold <= self.close_threshold:
            raise ValueError("open_threshold must be greater than close_threshold")
        if self.minimum_amplitude < 0 or self.minimum_duration_s < 0 or self.minimum_separation_s < 0 or self.refractory_s < 0 or self.maximum_gap_s < 0:
            raise ValueError("duration, gap, separation, refractory, and amplitude limits must be nonnegative")
        if self.maximum_duration_s is not None and self.maximum_duration_s < self.minimum_duration_s:
            raise ValueError("maximum_duration_s must be >= minimum_duration_s")
        if not 0 <= self.minimum_confidence <= 1:
            raise ValueError("minimum_confidence must be between zero and one")
        if self.smoothing_window < 1:
            raise ValueError("smoothing_window must be positive")


@dataclass(frozen=True)
class BiologicalEventCandidate:
    start_frame: int
    peak_frame: int
    end_frame: int | None
    start_time_s: float
    peak_time_s: float
    end_time_s: float | None
    baseline_value: float
    peak_value: float
    amplitude: float
    duration_s: float | None
    confidence: float | None
    cycle_state: str
    accepted: bool
    rejection_reasons: tuple[str, ...]


@dataclass(frozen=True)
class BiologicalEventDetectionResult:
    events: tuple[BiologicalEventCandidate, ...]
    summary: dict[str, float | int | None]
    configuration_sha256: str
    result_sha256: str


def _canonical_hash(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _smooth(samples: list[EventSignalSample], definition: CycleDefinition) -> list[EventSignalSample]:
    if definition.smoothing == "none" or definition.smoothing_window == 1:
        return samples
    result: list[EventSignalSample] = []
    segment: list[EventSignalSample] = []
    for sample in samples:
        if not sample.valid or sample.value is None:
            segment.clear(); result.append(sample); continue
        segment.append(sample)
        values = [s.value for s in segment[-definition.smoothing_window :] if s.value is not None]
        value = fmean(values) if definition.smoothing == "mean" else median(values)
        result.append(replace(sample, value=float(value)))
    return result


def _candidate(
    start: EventSignalSample,
    peak: EventSignalSample,
    end: EventSignalSample | None,
    baseline: float,
    state: str,
    confidences: list[float],
    definition: CycleDefinition,
    previous_end_time: float | None,
) -> BiologicalEventCandidate:
    duration = None if end is None else end.time_s - start.time_s
    amplitude = float(peak.value or 0) - baseline
    confidence = min(confidences) if confidences else None
    reasons: list[str] = []
    if state != "complete": reasons.append(state)
    if amplitude < definition.minimum_amplitude: reasons.append("minimum_amplitude")
    if duration is not None and duration < definition.minimum_duration_s: reasons.append("minimum_duration")
    if duration is not None and definition.maximum_duration_s is not None and duration > definition.maximum_duration_s: reasons.append("maximum_duration")
    if confidence is None or confidence < definition.minimum_confidence: reasons.append("minimum_confidence")
    if previous_end_time is not None and start.time_s - previous_end_time < max(definition.minimum_separation_s, definition.refractory_s): reasons.append("minimum_separation")
    return BiologicalEventCandidate(start.frame_index, peak.frame_index, None if end is None else end.frame_index, start.time_s, peak.time_s, None if end is None else end.time_s, baseline, float(peak.value or 0), amplitude, duration, confidence, state, not reasons, tuple(reasons))


def detect_biological_events(samples: list[EventSignalSample] | tuple[EventSignalSample, ...], definition: CycleDefinition) -> BiologicalEventDetectionResult:
    ordered = sorted(samples, key=lambda s: (s.time_s, s.frame_index))
    identities = {sample.animal_identity_id for sample in ordered}
    if len(identities) > 1:
        raise ValueError("Event detection requires samples from one identity")
    if not ordered:
        config_hash = _canonical_hash(asdict(definition))
        return BiologicalEventDetectionResult((), {"candidate_count": 0, "confirmed_eligible_count": 0, "frequency_hz": 0.0, "evaluated_duration_s": 0.0}, config_hash, _canonical_hash([]))
    ordered = _smooth(ordered, definition)
    events: list[BiologicalEventCandidate] = []
    active = False
    start: EventSignalSample | None = None
    peak: EventSignalSample | None = None
    baseline = definition.close_threshold
    last_closed_value = definition.close_threshold
    confidences: list[float] = []
    last_valid: EventSignalSample | None = None
    previous_end_time: float | None = None
    partial_start = False
    for sample in ordered:
        valid = sample.valid and sample.value is not None and math.isfinite(sample.value) and math.isfinite(sample.time_s)
        if not valid:
            if active and last_valid is not None and sample.time_s - last_valid.time_s > definition.maximum_gap_s:
                assert start is not None and peak is not None
                events.append(_candidate(start, peak, None, baseline, "partial_gap", confidences, definition, previous_end_time))
                active = False; start = peak = None; confidences = []
            continue
        if active and last_valid is not None and sample.time_s - last_valid.time_s > definition.maximum_gap_s:
            assert start is not None and peak is not None
            events.append(_candidate(start, peak, None, baseline, "partial_gap", confidences, definition, previous_end_time))
            active = False; start = peak = None; confidences = []
        if not active:
            if sample.value >= definition.open_threshold:
                active = True; start = peak = sample; baseline = last_closed_value
                partial_start = last_valid is None
                confidences = [sample.confidence] if sample.confidence is not None else []
            else:
                last_closed_value = sample.value
        else:
            if sample.confidence is not None: confidences.append(sample.confidence)
            assert peak is not None and start is not None
            if sample.value > (peak.value if peak.value is not None else -math.inf): peak = sample
            if sample.value <= definition.close_threshold:
                state = "partial_start" if partial_start else "complete"
                event = _candidate(start, peak, sample, baseline, state, confidences, definition, previous_end_time)
                events.append(event); previous_end_time = sample.time_s
                active = False; start = peak = None; confidences = []; last_closed_value = sample.value
        last_valid = sample
    if active:
        assert start is not None and peak is not None
        events.append(_candidate(start, peak, None, baseline, "partial_start" if partial_start else "partial_end", confidences, definition, previous_end_time))

    valid_times = [s.time_s for s in ordered if s.valid and s.value is not None]
    duration = max(valid_times) - min(valid_times) if len(valid_times) > 1 else 0.0
    accepted = [event for event in events if event.accepted and event.cycle_state == "complete"]
    summary: dict[str, float | int | None] = {
        "candidate_count": len(events), "confirmed_eligible_count": len(accepted),
        "complete_candidate_count": sum(e.cycle_state == "complete" for e in events),
        "partial_candidate_count": sum(e.cycle_state != "complete" for e in events),
        "mean_amplitude": fmean(e.amplitude for e in accepted) if accepted else None,
        "evaluated_duration_s": duration, "frequency_hz": len(accepted) / duration if duration > 0 else 0.0,
    }
    config_hash = _canonical_hash(asdict(definition))
    result_hash = _canonical_hash({"events": [asdict(e) for e in events], "summary": summary, "configuration_sha256": config_hash})
    return BiologicalEventDetectionResult(tuple(events), summary, config_hash, result_hash)
