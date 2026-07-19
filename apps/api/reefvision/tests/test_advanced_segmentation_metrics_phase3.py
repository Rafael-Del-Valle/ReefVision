from __future__ import annotations

import numpy as np
import pytest

from reefvision.ml.segmentation_metrics import (
    average_precision,
    area_stratum,
    boundary_metrics,
    confidence_calibration,
    panoptic_metrics,
)


def test_boundary_surface_and_panoptic_metrics() -> None:
    ground_truth = np.zeros((32, 32), dtype=bool)
    ground_truth[5:20, 5:20] = True
    prediction = np.zeros((32, 32), dtype=bool)
    prediction[6:21, 5:20] = True

    boundary = boundary_metrics(ground_truth, prediction, tolerance_pixels=1)
    assert boundary.precision > 0.9
    assert boundary.recall > 0.9
    assert boundary.f1 > 0.9
    assert boundary.hausdorff_distance == pytest.approx(1)
    assert boundary.average_symmetric_surface_distance is not None

    panoptic = panoptic_metrics(
        [0.8, 0.6],
        true_positive_count=2,
        false_positive_count=1,
        false_negative_count=1,
    )
    assert panoptic.segmentation_quality == pytest.approx(0.7)
    assert panoptic.recognition_quality == pytest.approx(2 / 3)
    assert panoptic.panoptic_quality == pytest.approx(0.7 * 2 / 3)


def test_calibration_average_precision_and_size_strata() -> None:
    bins, expected_error = confidence_calibration(
        [(0.95, True), (0.8, True), (0.7, False), (0.1, False)],
        bin_count=5,
    )
    assert sum(item.count for item in bins) == 4
    assert 0 <= expected_error <= 1

    score = average_precision(
        [(0.95, True), (0.9, False), (0.7, True)],
        ground_truth_count=2,
    )
    assert score == pytest.approx(5 / 6)
    assert area_stratum(500, small_max_pixels=1024, large_min_pixels=9216) == "small"
    assert area_stratum(5000, small_max_pixels=1024, large_min_pixels=9216) == "medium"
    assert area_stratum(10000, small_max_pixels=1024, large_min_pixels=9216) == "large"
