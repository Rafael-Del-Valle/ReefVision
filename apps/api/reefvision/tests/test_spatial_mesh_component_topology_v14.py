"""Per-patch topology defects must remain visible in unverified mesh previews."""

from __future__ import annotations

from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview


def _preview(vertices: list[list[float]], faces: list[list[int]]) -> dict:
    return measure_mesh_preview(
        vertices=vertices,
        faces=faces,
        meters_per_unit=0.01,
        calibration_method="ruler",
        calibration_evidence="Provisional field scale awaiting human verification",
        relative_scale_uncertainty=0.05,
    )


def test_winding_defect_is_localized_to_one_patch() -> None:
    result = _preview(
        vertices=[
            [0, 0, 0],
            [1, 0, 0],
            [0, 1, 0],
            [0, -1, 0],
            [10, 0, 0],
            [11, 0, 0],
            [10, 1, 0],
        ],
        faces=[[0, 1, 2], [0, 1, 3], [4, 5, 6]],
    )
    assert result["edge_connected_patch_face_counts"] == [2, 1]
    assert result["edge_connected_patch_boundary_edge_counts"] == [4, 3]
    assert result["edge_connected_patch_nonmanifold_edge_counts"] == [0, 0]
    assert result["edge_connected_patch_inconsistent_winding_edge_counts"] == [1, 0]
    assert sum(result["edge_connected_patch_boundary_edge_counts"]) == result["boundary_edge_count"]
    assert (
        sum(result["edge_connected_patch_inconsistent_winding_edge_counts"])
        == result["inconsistent_winding_edge_count"]
    )
    assert "inconsistent_face_winding" in result["qc_warnings"]
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert result["provenance"]["calibration_verified"] is False


def test_nonmanifold_edge_is_localized_to_one_patch() -> None:
    result = _preview(
        vertices=[
            [0, 0, 0],
            [1, 0, 0],
            [0, 1, 0],
            [0, -1, 0],
            [0, 0, 1],
            [10, 0, 0],
            [11, 0, 0],
            [10, 1, 0],
        ],
        faces=[[0, 1, 2], [1, 0, 3], [0, 1, 4], [5, 6, 7]],
    )
    assert result["edge_connected_patch_face_counts"] == [3, 1]
    assert result["edge_connected_patch_boundary_edge_counts"] == [6, 3]
    assert result["edge_connected_patch_nonmanifold_edge_counts"] == [1, 0]
    assert result["edge_connected_patch_inconsistent_winding_edge_counts"] == [0, 0]
    assert (
        sum(result["edge_connected_patch_nonmanifold_edge_counts"])
        == result["nonmanifold_edge_count"]
    )
    assert "nonmanifold_mesh_edges" in result["qc_warnings"]
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert result["provenance"]["calibration_verified"] is False


def test_degenerate_face_is_localized_to_one_patch() -> None:
    result = _preview(
        vertices=[
            [0, 0, 0],
            [1, 0, 0],
            [0, 1, 0],
            [10, 0, 0],
            [11, 0, 0],
            [12, 0, 0],
        ],
        faces=[[0, 1, 2], [3, 4, 5]],
    )
    assert result["edge_connected_patch_face_counts"] == [1, 1]
    assert result["edge_connected_patch_degenerate_face_counts"] == [0, 1]
    assert (
        sum(result["edge_connected_patch_degenerate_face_counts"])
        == result["degenerate_face_count"]
    )
    assert result["edge_connected_patch_surface_areas_m2"] == [0.00005, 0.0]
    assert "degenerate_triangles_present" in result["qc_warnings"]
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert result["provenance"]["calibration_verified"] is False


def test_patch_fingerprints_ignore_vertex_and_face_order() -> None:
    original = _preview(
        vertices=[
            [0, 0, 0],
            [1, 0, 0],
            [0, 1, 0],
            [10, 0, 0],
            [12, 0, 0],
            [10, 2, 0],
        ],
        faces=[[0, 1, 2], [3, 4, 5]],
    )
    reordered = _preview(
        vertices=[
            [10, 2, 0],
            [0, 1, 0],
            [12, 0, 0],
            [1, 0, 0],
            [10, 0, 0],
            [0, 0, 0],
        ],
        faces=[[4, 0, 2], [1, 3, 5]],
    )
    key = "edge_connected_patch_geometry_sha256"
    assert len(original[key]) == 2
    assert all(len(fingerprint) == 64 for fingerprint in original[key])
    assert original[key][0] != original[key][1]
    assert sorted(original[key]) == sorted(reordered[key])
    assert original["measurement_status"] == "caller_supplied_unverified"
    assert reordered["provenance"]["calibration_verified"] is False
