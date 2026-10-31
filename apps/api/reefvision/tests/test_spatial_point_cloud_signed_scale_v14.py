"""Signed bounds regression for 1.4 point-cloud scale uncertainty."""

from __future__ import annotations

import pytest

from reefvision.services.spatial_point_cloud_v14 import measure_point_cloud_preview


def test_signed_coordinate_intervals() -> None:
    result = measure_point_cloud_preview(
        points=[[-2, -3, -4], [1, 2, 3]],
        meters_per_unit=0.01,
        calibration_method="ruler",
        calibration_evidence="Unverified",
        relative_scale_uncertainty=0.1,
    )
    assert result["axis_aligned_min_in_source_frame_scale_interval_m"][0] == pytest.approx(
        [-0.022, -0.018]
    )
    assert result["axis_aligned_max_in_source_frame_scale_interval_m"][0] == pytest.approx(
        [0.009, 0.011]
    )
    assert result["provenance"]["calibration_verified"] is False
