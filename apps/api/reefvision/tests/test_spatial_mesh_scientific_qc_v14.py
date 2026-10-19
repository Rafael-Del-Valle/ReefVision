"""Scientific geometry QC regressions for unverified mesh previews."""

from __future__ import annotations

import pytest

from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview


def test_nonmanifold_edge_is_reported_without_verification() -> None:
    result = measure_mesh_preview(
        vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [0, -1, 0]],
        faces=[[0, 1, 2], [1, 0, 3], [0, 1, 4]],
        meters_per_unit=0.01,
        calibration_method="ruler",
        calibration_evidence="Provisional control measurement",
    )
    assert result["nonmanifold_edge_count"] == 1
    assert "nonmanifold_mesh_edges" in result["qc_warnings"]
    assert result["measurement_status"] == "caller_supplied_unverified"


def test_area_scales_quadratically_and_uncertainty_is_not_ci() -> None:
    kwargs = {
        "vertices": [[0, 0, 0], [2, 0, 0], [0, 3, 0]],
        "faces": [[0, 1, 2]],
        "calibration_method": "ruler",
        "calibration_evidence": "Provisional control measurement",
        "relative_scale_uncertainty": 0.1,
    }
    small = measure_mesh_preview(**kwargs, meters_per_unit=0.01)
    large = measure_mesh_preview(**kwargs, meters_per_unit=0.02)
    assert large["surface_area_m2"] == pytest.approx(4 * small["surface_area_m2"])
    assert large["area_scale_uncertainty_m2"] == pytest.approx(0.2 * large["surface_area_m2"])
    assert large["confidence_interval"] is None
    assert large["provenance"]["calibration_verified"] is False
