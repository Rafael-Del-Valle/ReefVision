"""Scientific regression: unordered cloud identity is not ordered point identity."""

from __future__ import annotations

import pytest

from reefvision.services.spatial_point_cloud_v14 import measure_point_cloud_preview


def _preview(points: list[list[float]]) -> dict:
    return measure_point_cloud_preview(
        points=points,
        meters_per_unit=0.1,
        calibration_method="ruler",
        calibration_evidence="Unverified source-frame ruler",
        relative_scale_uncertainty=0.1,
        point_index_pairs=[[0, 1]],
    )


def test_permuted_cloud_retains_geometry_hash_but_not_point_order() -> None:
    original = _preview([[-2.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 4.0, 0.0]])
    permuted = _preview([[1.0, 4.0, 0.0], [-2.0, 0.0, 0.0], [1.0, 0.0, 0.0]])

    assert original["provenance"]["geometry_sha256"] == permuted["provenance"]["geometry_sha256"]
    assert (
        original["provenance"]["ordered_geometry_sha256"]
        != permuted["provenance"]["ordered_geometry_sha256"]
    )
    assert original["axis_aligned_dimensions_m"] == pytest.approx(
        permuted["axis_aligned_dimensions_m"]
    )
    assert original["selected_point_chords"][0]["chord_distance_m"] == pytest.approx(0.3)
    assert permuted["selected_point_chords"][0]["chord_distance_m"] == pytest.approx(0.5)
    assert original["selected_point_chords"][0]["chord_distance_scale_interval_m"] == pytest.approx(
        [0.27, 0.33]
    )
    assert permuted["selected_point_chords"][0]["chord_distance_scale_interval_m"] == pytest.approx(
        [0.45, 0.55]
    )
    assert original["measurement_status"] == "caller_supplied_unverified"
    assert permuted["provenance"]["coordinate_registration_verified"] is False
    assert original["branch_length_m"] is None
    assert permuted["surface_area_m2"] is None
