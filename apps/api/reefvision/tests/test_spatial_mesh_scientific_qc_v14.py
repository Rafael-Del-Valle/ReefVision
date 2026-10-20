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


@pytest.mark.parametrize(
    ("faces", "expected_winding"),
    [
        ([[0, 1, 2], [0, 2, 3]], 0),
        ([[0, 1, 2], [0, 3, 2]], 1),
    ],
)
def test_shared_edge_orientation_qc(faces: list[list[int]], expected_winding: int) -> None:
    result = measure_mesh_preview(
        vertices=[[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
        faces=faces,
        meters_per_unit=0.01,
        calibration_method="ruler",
        calibration_evidence="Provisional control measurement",
    )
    assert result["edge_connected_patch_count"] == 1
    assert result["inconsistent_winding_edge_count"] == expected_winding
    assert ("inconsistent_face_winding" in result["qc_warnings"]) == bool(expected_winding)
    assert result["measurement_status"] == "caller_supplied_unverified"


def test_disconnected_surface_patches_are_not_silently_combined() -> None:
    result = measure_mesh_preview(
        vertices=[
            [0, 0, 0],
            [1, 0, 0],
            [0, 1, 0],
            [10, 0, 0],
            [11, 0, 0],
            [10, 1, 0],
        ],
        faces=[[0, 1, 2], [3, 4, 5]],
        meters_per_unit=0.01,
        calibration_method="ruler",
        calibration_evidence="Provisional control measurement",
    )
    assert result["edge_connected_patch_count"] == 2
    assert result["inconsistent_winding_edge_count"] == 0
    assert "disconnected_mesh_patches" in result["qc_warnings"]
    assert result["provenance"]["calibration_verified"] is False


def test_unreferenced_outlier_cannot_inflate_calibrated_dimensions() -> None:
    result = measure_mesh_preview(
        vertices=[[0, 0, 0], [2, 0, 0], [0, 3, 0], [1000, 1000, 1000]],
        faces=[[0, 1, 2]],
        meters_per_unit=0.01,
        calibration_method="ruler",
        calibration_evidence="Provisional control measurement",
        relative_scale_uncertainty=0.1,
    )
    assert result["vertex_count"] == 4
    assert result["unreferenced_vertex_count"] == 1
    assert result["axis_aligned_dimensions_m"] == pytest.approx([0.02, 0.03, 0.0])
    assert result["axis_aligned_dimension_scale_uncertainty_m"] == pytest.approx(
        [0.002, 0.003, 0.0]
    )
    assert result["surface_area_m2"] == pytest.approx(0.0003)
    assert "unreferenced_mesh_vertices" in result["qc_warnings"]
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert result["provenance"]["calibration_verified"] is False


def test_disconnected_patch_areas_and_uncertainties_are_reported_separately() -> None:
    result = measure_mesh_preview(
        vertices=[
            [0, 0, 0],
            [2, 0, 0],
            [0, 3, 0],
            [10, 0, 0],
            [14, 0, 0],
            [10, 5, 0],
        ],
        faces=[[0, 1, 2], [3, 4, 5]],
        meters_per_unit=0.01,
        calibration_method="ruler",
        calibration_evidence="Unreviewed field scale",
        relative_scale_uncertainty=0.05,
    )
    assert result["edge_connected_patch_count"] == 2
    assert result["edge_connected_patch_face_counts"] == [1, 1]
    assert result["edge_connected_patch_surface_areas_m2"] == pytest.approx([0.0003, 0.001])
    assert result["edge_connected_patch_axis_aligned_dimensions_m"] == [
        pytest.approx([0.02, 0.03, 0.0]),
        pytest.approx([0.04, 0.05, 0.0]),
    ]
    assert result["edge_connected_patch_dimension_scale_uncertainties_m"] == [
        pytest.approx([0.001, 0.0015, 0.0]),
        pytest.approx([0.002, 0.0025, 0.0]),
    ]
    assert result["edge_connected_patch_area_scale_uncertainties_m2"] == pytest.approx(
        [0.00003, 0.0001]
    )
    assert sum(result["edge_connected_patch_surface_areas_m2"]) == pytest.approx(
        result["surface_area_m2"]
    )
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert result["provenance"]["calibration_verified"] is False


def test_patch_scale_uncertainty_is_unknown_when_scale_error_is_unspecified() -> None:
    result = measure_mesh_preview(
        vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0]],
        faces=[[0, 1, 2]],
        meters_per_unit=0.01,
        calibration_method="ruler",
        calibration_evidence="Unreviewed scale",
    )
    assert result["edge_connected_patch_surface_areas_m2"] == pytest.approx([0.00005])
    assert result["edge_connected_patch_area_scale_uncertainties_m2"] is None
    assert result["edge_connected_patch_dimension_scale_uncertainties_m"] is None
    assert result["confidence_interval"] is None


def test_multiple_faces_in_one_patch_keep_area_and_scale_uncertainty_consistent() -> None:
    # Two faces share an edge; a third face belongs to a separate patch.
    result = measure_mesh_preview(
        vertices=[
            [0, 0, 0],
            [2, 0, 0],
            [2, 2, 0],
            [0, 2, 0],
            [10, 0, 0],
            [12, 0, 0],
            [10, 3, 0],
        ],
        faces=[[0, 1, 2], [0, 2, 3], [4, 5, 6]],
        meters_per_unit=0.01,
        calibration_method="ruler",
        calibration_evidence="Provisional common scale",
        relative_scale_uncertainty=0.1,
    )
    assert result["edge_connected_patch_count"] == 2
    assert result["edge_connected_patch_face_counts"] == [2, 1]
    assert result["edge_connected_patch_surface_areas_m2"] == pytest.approx([0.0004, 0.0003])
    assert result["edge_connected_patch_area_scale_uncertainties_m2"] == pytest.approx(
        [0.00008, 0.00006]
    )
    assert sum(result["edge_connected_patch_surface_areas_m2"]) == pytest.approx(
        result["surface_area_m2"]
    )
    assert sum(result["edge_connected_patch_area_scale_uncertainties_m2"]) == pytest.approx(
        result["area_scale_uncertainty_m2"]
    )
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert result["provenance"]["calibration_verified"] is False
