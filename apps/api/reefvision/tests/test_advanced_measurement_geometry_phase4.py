from __future__ import annotations

import math

import numpy as np
import pytest

from reefvision.ml.measurement_geometry import (
    calibrate_references,
    shape_measurements,
    skeleton_measurements,
    surface_area_estimate,
)


def test_shape_and_branch_measurements_on_known_geometry() -> None:
    mask = np.zeros((80, 100), dtype=bool)
    mask[20:60, 30:70] = True
    shape = shape_measurements(mask)
    assert shape.area_pixels == 1600
    assert shape.perimeter_pixels == pytest.approx(160)
    assert shape.bounding_width_pixels == 40
    assert shape.bounding_height_pixels == 40
    assert shape.solidity > 0.9
    assert shape.feret_max_pixels > 50

    branching = np.zeros((80, 80), dtype=bool)
    branching[10:70, 39:42] = True
    branching[35:38, 15:65] = True
    _, skeleton = skeleton_measurements(
        branching,
        prune_spurs_pixels=0,
        bridge_gaps_pixels=0,
    )
    assert skeleton.total_length_pixels > 90
    assert skeleton.longest_path_pixels > 50
    assert skeleton.endpoint_count >= 4
    assert skeleton.junction_count >= 1
    assert skeleton.branch_count >= 4


def test_multi_reference_calibration_and_surface_models_include_uncertainty() -> None:
    calibration = calibrate_references(
        [(100, 10.0), (200, 20.2), (300, 29.8)],
        unit="mm",
    )
    assert calibration.distance_per_pixel == pytest.approx(0.1, rel=0.02)
    assert calibration.reference_count == 3
    assert calibration.residual_standard_error is not None
    assert calibration.lower_95 is not None
    assert calibration.upper_95 is not None

    cylindrical = surface_area_estimate(
        method="cylindrical",
        projected_area=100,
        perimeter=40,
        centerline_length=30,
        diameter_major=4,
        uncertainty_fraction=0.05,
        unit="mm",
    )
    assert cylindrical.area == pytest.approx(math.pi * 4 * 30)
    assert cylindrical.standard_uncertainty == pytest.approx(cylindrical.area * 0.05)
    assert cylindrical.unit_squared == "mm²"

    elliptical = surface_area_estimate(
        method="elliptical_cylinder",
        projected_area=100,
        perimeter=40,
        centerline_length=30,
        diameter_major=5,
        diameter_minor=3,
    )
    assert elliptical.area is not None
    assert elliptical.area > 0
