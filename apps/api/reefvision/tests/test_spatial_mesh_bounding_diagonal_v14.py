"""Regression tests for calibrated mesh bounding-box diagonals."""

from math import sqrt

import pytest

from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview


def test_bounding_diagonals_are_calibrated_and_exclude_unused_vertices() -> None:
    result = measure_mesh_preview(
        vertices=[[0, 0, 0], [2, 0, 0], [0, 3, 0], [100, 100, 100]],
        faces=[[0, 1, 2]],
        meters_per_unit=0.01,
        calibration_method="ruler",
        calibration_evidence="Unreviewed scale",
        relative_scale_uncertainty=0.1,
    )
    diagonal = 0.01 * sqrt(13)
    assert result["axis_aligned_bounding_box_diagonal_m"] == pytest.approx(diagonal)
    assert result["axis_aligned_bounding_box_diagonal_scale_uncertainty_m"] == pytest.approx(
        diagonal * 0.1
    )
    assert result["edge_connected_patch_bounding_box_diagonals_m"] == pytest.approx([diagonal])
    assert result["unreferenced_vertex_count"] == 1
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert result["provenance"]["calibration_verified"] is False


def test_unknown_scale_uncertainty_remains_null() -> None:
    result = measure_mesh_preview(
        vertices=[[0, 0, 0], [2, 0, 0], [0, 3, 0]],
        faces=[[0, 1, 2]],
        meters_per_unit=0.01,
        calibration_method="ruler",
        calibration_evidence="Unreviewed scale",
    )
    assert result["axis_aligned_bounding_box_diagonal_scale_uncertainty_m"] is None
    assert result["edge_connected_patch_bounding_box_diagonal_scale_uncertainties_m"] is None
