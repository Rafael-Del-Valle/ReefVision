"""Deterministic CPU engineering benchmark for ReefPose Phase 5 scalar analysis."""

from __future__ import annotations

import json
import math
from time import perf_counter

from reefvision.domain.pose_anatomical_measurement import (
    AnatomicalLandmark,
    AnatomicalObservation,
    MeasurementDefinition,
    calculate_measurement_series,
)
from reefvision.domain.pose_biological_events import (
    CycleDefinition,
    EventSignalSample,
    detect_biological_events,
)


def main() -> None:
    frame_count = 10_000
    fps = 120.0
    observations = [
        AnatomicalObservation(
            observation_id=f"synthetic-{frame}",
            revision=1,
            animal_identity_id="synthetic-animal",
            frame_index=frame,
            time_s=frame / fps,
            coordinate_space="source_pixels",
            association_confidence=0.95,
            landmarks=(
                AnatomicalLandmark("upper_jaw", 20.0, 20.0, 0.95),
                AnatomicalLandmark(
                    "lower_jaw",
                    20.0,
                    25.0 + 4.0 * math.sin(2.0 * math.pi * 2.0 * frame / fps),
                    0.92,
                ),
            ),
        )
        for frame in range(frame_count)
    ]
    definition = MeasurementDefinition("gape", "distance", ("upper_jaw", "lower_jaw"))
    started = perf_counter()
    measured = calculate_measurement_series(
        observations,
        definition,
        identity_id="synthetic-animal",
    )
    measurement_seconds = perf_counter() - started
    signal = [
        EventSignalSample(
            frame_index=sample.frame_index,
            time_s=sample.time_s,
            value=sample.pixel_value,
            confidence=sample.confidence,
            valid=sample.valid,
            animal_identity_id="synthetic-animal",
        )
        for sample in measured.samples
    ]
    cycle = CycleDefinition(
        open_threshold=6.0,
        close_threshold=4.0,
        minimum_amplitude=2.0,
        minimum_duration_s=0.05,
        maximum_gap_s=0.1,
    )
    started = perf_counter()
    detected = detect_biological_events(signal, cycle)
    event_seconds = perf_counter() - started
    print(
        json.dumps(
            {
                "fixture": "synthetic_engineering",
                "frame_count": frame_count,
                "measurement_seconds": measurement_seconds,
                "measurement_samples_per_second": frame_count / measurement_seconds,
                "event_seconds": event_seconds,
                "event_samples_per_second": frame_count / event_seconds,
                "complete_cycles": detected.summary["confirmed_eligible_count"],
                "partial_cycles": detected.summary["partial_candidate_count"],
                "configuration_sha256": detected.configuration_sha256,
                "result_sha256": detected.result_sha256,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
