from __future__ import annotations

import pytest

from reefvision.domain.pose_biological_events import (
    CycleDefinition,
    EventSignalSample,
    detect_biological_events,
)


def samples(
    values: list[float | None], *, dt: float = 0.1, identity: str = "fish-1"
) -> list[EventSignalSample]:
    return [
        EventSignalSample(
            i, i * dt, value, 0.9 if value is not None else None, value is not None, identity
        )
        for i, value in enumerate(values)
    ]


def definition(**changes: object) -> CycleDefinition:
    values = dict(
        open_threshold=6.0,
        close_threshold=3.0,
        minimum_amplitude=4.0,
        minimum_duration_s=0.1,
        maximum_duration_s=2.0,
        maximum_gap_s=0.25,
    )
    values.update(changes)
    return CycleDefinition(**values)


def test_counts_known_fish_gape_cycles_once_each() -> None:
    result = detect_biological_events(samples([1, 2, 7, 9, 8, 2, 1, 7, 10, 9, 2, 1]), definition())
    assert result.summary["confirmed_eligible_count"] == 2
    assert [(e.start_frame, e.peak_frame, e.end_frame) for e in result.events] == [
        (2, 3, 5),
        (7, 8, 10),
    ]
    assert all(e.cycle_state == "complete" and e.accepted for e in result.events)
    assert result.summary["frequency_hz"] == pytest.approx(2 / 1.1)


def test_sustained_open_is_one_cycle_and_duration_or_amplitude_rejections_are_retained() -> None:
    one = detect_biological_events(samples([1, 7, 8, 9, 8, 7, 2]), definition())
    assert len(one.events) == 1
    rejected = detect_biological_events(samples([2, 7, 4, 2]), definition(minimum_amplitude=8))
    assert rejected.summary["confirmed_eligible_count"] == 0
    assert rejected.events[0].accepted is False
    assert "minimum_amplitude" in rejected.events[0].rejection_reasons


def test_short_gap_preserves_cycle_without_interpolation_long_gap_yields_partial() -> None:
    short = detect_biological_events(samples([1, 7, None, 9, 2]), definition(maximum_gap_s=0.25))
    assert len(short.events) == 1
    assert short.events[0].cycle_state == "complete"
    assert short.events[0].peak_frame == 3
    long = detect_biological_events(
        samples([1, 7, None, None, None, 2]), definition(maximum_gap_s=0.15)
    )
    assert len(long.events) == 1
    assert long.events[0].cycle_state == "partial_gap"
    assert long.events[0].accepted is False


def test_start_and_end_partials_and_low_confidence_are_never_confirmed() -> None:
    start = detect_biological_events(samples([8, 9, 2]), definition())
    end = detect_biological_events(samples([1, 7, 9]), definition())
    assert start.events[0].cycle_state == "partial_start"
    assert end.events[0].cycle_state == "partial_end"
    low = samples([1, 7, 9, 2])
    low[2] = EventSignalSample(2, 0.2, 9, 0.2, True, "fish-1")
    result = detect_biological_events(low, definition(minimum_confidence=0.5))
    assert result.events[0].accepted is False
    assert "minimum_confidence" in result.events[0].rejection_reasons


def test_complete_cycle_requires_observed_closed_baseline_and_long_gaps_reset_readiness() -> None:
    ambiguous = detect_biological_events(samples([4, 7, 2]), definition())
    assert ambiguous.events[0].cycle_state == "partial_start"
    assert ambiguous.summary["confirmed_eligible_count"] == 0

    irregular = [
        EventSignalSample(0, 0.0, 1, 0.9, True, "fish-1"),
        EventSignalSample(1, 0.1, None, None, False, "fish-1"),
        EventSignalSample(2, 10.0, 8, 0.9, True, "fish-1"),
        EventSignalSample(3, 10.1, 2, 0.9, True, "fish-1"),
    ]
    after_gap = detect_biological_events(irregular, definition(maximum_gap_s=0.25))
    assert after_gap.events[0].cycle_state == "partial_start"
    assert after_gap.summary["confirmed_eligible_count"] == 0
    assert after_gap.summary["evaluated_duration_s"] == pytest.approx(0.1)


def test_smoothing_is_deterministic_and_identities_cannot_mix() -> None:
    with pytest.raises(ValueError, match="one identity"):
        detect_biological_events(
            samples([1, 7, 2]) + samples([1, 8, 2], identity="fish-2"), definition()
        )
    a = detect_biological_events(
        samples([1, 5.9, 6.1, 5.9, 8, 2]), definition(smoothing="median", smoothing_window=3)
    )
    b = detect_biological_events(
        samples([1, 5.9, 6.1, 5.9, 8, 2]), definition(smoothing="median", smoothing_window=3)
    )
    assert a.result_sha256 == b.result_sha256


def test_definition_rejects_invalid_hysteresis() -> None:
    with pytest.raises(ValueError, match="open_threshold"):
        definition(open_threshold=2, close_threshold=3)
