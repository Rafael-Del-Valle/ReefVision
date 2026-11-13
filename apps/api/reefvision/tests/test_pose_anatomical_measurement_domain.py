from __future__ import annotations

import math

import pytest

from reefvision.domain.pose_anatomical_measurement import (
    AnatomicalLandmark,
    AnatomicalObservation,
    MeasurementCalibration,
    MeasurementDefinition,
    calculate_measurement_series,
)


def obs(
    frame: int, time: float, points: dict[str, tuple[float, float]], identity: str = "fish-1"
) -> AnatomicalObservation:
    return AnatomicalObservation(
        observation_id=f"o-{identity}-{frame}",
        revision=1,
        animal_identity_id=identity,
        frame_index=frame,
        time_s=time,
        coordinate_space="source_pixels",
        association_confidence=0.8,
        landmarks=tuple(AnatomicalLandmark(k, x, y, 0.9) for k, (x, y) in points.items()),
    )


def test_distance_angle_calibration_and_confidence() -> None:
    observations = [obs(0, 0, {"a": (0, 0), "b": (3, 4), "c": (3, 0)})]
    distance = calculate_measurement_series(
        observations,
        MeasurementDefinition("d", "distance", ("a", "b")),
        MeasurementCalibration(2, "mm"),
    )
    angle = calculate_measurement_series(
        observations, MeasurementDefinition("a", "angle", ("a", "c", "b"))
    )
    assert distance.samples[0].pixel_value == 5
    assert distance.samples[0].physical_value == 2.5
    assert distance.samples[0].confidence == 0.8
    assert angle.samples[0].pixel_value == pytest.approx(90)


def test_irregular_velocity_displacement_orientation_and_angular_velocity() -> None:
    observations = [
        obs(0, 0, {"p": (0, 0), "q": (1, 0)}),
        obs(1, 0.5, {"p": (3, 4), "q": (3, 5)}),
        obs(2, 2, {"p": (6, 8), "q": (5, 8)}),
    ]
    velocity = calculate_measurement_series(
        observations, MeasurementDefinition("v", "velocity", ("p",))
    )
    displacement = calculate_measurement_series(
        observations, MeasurementDefinition("x", "displacement", ("p",))
    )
    orientation = calculate_measurement_series(
        observations, MeasurementDefinition("o", "body_axis_orientation", ("p", "q"))
    )
    omega = calculate_measurement_series(
        observations, MeasurementDefinition("w", "angular_velocity", ("p", "q"))
    )
    assert velocity.samples[1].pixel_value == 10
    assert velocity.samples[2].pixel_value == pytest.approx(10 / 3)
    assert displacement.samples[2].pixel_value == 10
    assert orientation.samples[1].pixel_value == 90
    assert omega.samples[2].pixel_value == pytest.approx(60)


def test_curvature_extension_relative_movement_missing_and_identity_isolation() -> None:
    observations = [
        obs(0, 0, {"a": (0, 0), "b": (1, 0), "c": (1, 1)}),
        obs(1, 1, {"a": (0, 0), "b": (2, 0), "c": (2, 2)}),
        obs(0, 0, {"a": (50, 50), "b": (60, 50), "c": (60, 60)}, "fish-2"),
    ]
    curvature = calculate_measurement_series(
        observations, MeasurementDefinition("c", "curvature", ("a", "b", "c")), identity_id="fish-1"
    )
    extension = calculate_measurement_series(
        observations, MeasurementDefinition("e", "extension", ("a", "b", "c")), identity_id="fish-1"
    )
    relative = calculate_measurement_series(
        observations,
        MeasurementDefinition("r", "relative_movement", ("a", "c")),
        identity_id="fish-1",
    )
    assert curvature.samples[0].pixel_value == pytest.approx(math.pi / 2)
    assert extension.samples[0].pixel_value == pytest.approx(math.sqrt(2) / 2)
    assert relative.samples[1].pixel_value == pytest.approx(math.sqrt(8) - math.sqrt(2))
    assert len(curvature.samples) == 2

    missing = calculate_measurement_series(
        [obs(0, 0, {"a": (0, 0)})], MeasurementDefinition("d", "distance", ("a", "b"))
    )
    assert missing.samples[0].valid is False
    assert "missing_landmark" in missing.samples[0].quality_flags


def test_rejects_non_source_coordinates_and_nonpositive_time() -> None:
    bad = obs(0, 0, {"p": (0, 0)})
    object.__setattr__(bad, "coordinate_space", "normalized")
    with pytest.raises(ValueError, match="source_pixels"):
        calculate_measurement_series([bad], MeasurementDefinition("d", "displacement", ("p",)))
    series = calculate_measurement_series(
        [obs(0, 1, {"p": (0, 0)}), obs(1, 1, {"p": (1, 0)})],
        MeasurementDefinition("v", "velocity", ("p",)),
    )
    assert series.samples[1].valid is False
    assert "nonpositive_time_delta" in series.samples[1].quality_flags
