"""Edge connectivity must not turn vertex-touching coral patches into one surface."""

from __future__ import annotations

import pytest

from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview


def test_vertex_touching_patches_remain_distinct_and_unverified() -> None:
    result = measure_mesh_preview(
        vertices=[
            [0, 0, 0],
            [1, 0, 0],
            [0, 1, 0],
            [-1, 0, 0],
            [0, -1, 0],
        ],
        faces=[[0, 1, 2], [0, 3, 4]],
        meters_per_unit=0.01,
        calibration_method="ruler",
        calibration_evidence="Unreviewed field scale",
        relative_scale_uncertainty=0.05,
    )
    assert result["edge_connected_patch_count"] == 2
    assert result["surface_area_m2"] == pytest.approx(0.0001)
    assert result["area_scale_uncertainty_m2"] == pytest.approx(0.00001)
    assert "disconnected_mesh_patches" in result["qc_warnings"]
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert result["provenance"]["calibration_verified"] is False
