from __future__ import annotations

import numpy as np
import pytest

from reefvision.services.scientific_3d import (
    allows_physical_measurement_claim,
    group_3d_frame_metrics,
    robust_track_depth,
    scientific_depth_tier,
)


def test_metric_model_is_not_automatically_a_validated_physical_measurement() -> None:
    tier = scientific_depth_tier(
        metric_model=True,
        camera_intrinsics_present=True,
        physical_reference_validated=False,
    )
    assert tier == "model_estimated_metric"
    assert allows_physical_measurement_claim(tier) is False


def test_calibrated_metric_requires_intrinsics_and_validated_reference() -> None:
    tier = scientific_depth_tier(
        metric_model=True,
        camera_intrinsics_present=True,
        physical_reference_validated=True,
    )
    assert tier == "calibrated_metric"
    assert allows_physical_measurement_claim(tier) is True


def test_robust_track_depth_uses_core_median_and_rejects_outlier_background() -> None:
    frame = np.full((20, 20), 2.0, dtype=np.float32)
    frame[0:4, :] = 30.0
    frame[:, 0:4] = 30.0
    frame[10, 10] = 1000.0
    frame[9, 9] = np.nan

    result = robust_track_depth(frame, [2, 2, 18, 18], core_fraction=0.5)

    assert result.depth == pytest.approx(2.0)
    assert result.valid_fraction > 0.9
    assert result.sample_count > 0
    assert 0 <= result.confidence <= 1


def test_robust_track_depth_fails_closed_when_valid_coverage_is_too_low() -> None:
    frame = np.zeros((10, 10), dtype=np.float32)
    frame[5, 5] = 2.0

    with pytest.raises(ValueError, match="insufficient valid positive depth pixels"):
        robust_track_depth(
            frame,
            [0, 0, 10, 10],
            core_fraction=1.0,
            minimum_valid_fraction=0.25,
        )


def test_group_3d_frame_metrics_are_computed_from_xyz_positions() -> None:
    result = group_3d_frame_metrics(
        [
            [0.0, 0.0, 1.0],
            [1.0, 0.0, 1.0],
            [0.0, 2.0, 1.0],
        ]
    )

    assert result.individual_count == 3
    assert result.centroid_x == pytest.approx(1 / 3)
    assert result.centroid_y == pytest.approx(2 / 3)
    assert result.centroid_z == pytest.approx(1.0)
    assert result.mean_nearest_neighbor_distance > 0
    assert result.mean_pairwise_distance > 0
    assert result.bounding_box_volume == pytest.approx(0.0)
