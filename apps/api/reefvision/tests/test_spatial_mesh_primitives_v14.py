import pytest

from reefvision.services.spatial_mesh_measurements import triangle_area


def test_area():
    assert triangle_area((0, 0, 0), (2, 0, 0), (0, 3, 0)) == 3


def test_degenerate_triangle():
    assert triangle_area((0, 0, 0), (1, 1, 1), (2, 2, 2)) == 0


def test_nonfinite_coordinate():
    with pytest.raises(ValueError, match="finite"):
        triangle_area((0, 0, 0), (1, 0, 0), (float("nan"), 1, 0))


def test_independent_calibrated_cube_reference_area_and_extent() -> None:
    """A 2-unit cube has six faces, independent of its 12 triangle facets."""
    from math import sqrt

    from reefvision.schemas.spatial_mesh_preview_v14 import MeshPreviewRequest
    from reefvision.services.spatial_mesh_surface_v14 import preview_from_request

    vertices = [
        [0, 0, 0],
        [2, 0, 0],
        [2, 2, 0],
        [0, 2, 0],
        [0, 0, 2],
        [2, 0, 2],
        [2, 2, 2],
        [0, 2, 2],
    ]
    faces = [
        [0, 2, 1],
        [0, 3, 2],
        [4, 5, 6],
        [4, 6, 7],
        [0, 1, 5],
        [0, 5, 4],
        [1, 2, 6],
        [1, 6, 5],
        [2, 3, 7],
        [2, 7, 6],
        [3, 0, 4],
        [3, 4, 7],
    ]
    measurement = preview_from_request(
        MeshPreviewRequest(
            vertices=vertices,
            faces=faces,
            meters_per_unit=0.01,
            calibration_method="ruler",
            calibration_evidence="Synthetic 2-unit cube; independent reference",
            relative_scale_uncertainty=0.1,
        )
    )
    assert measurement["surface_area_m2"] == pytest.approx(6 * (2 * 0.01) ** 2)
    assert measurement["axis_aligned_bounding_box_diagonal_m"] == pytest.approx(sqrt(3) * 0.02)
    assert measurement["area_scale_uncertainty_m2"] == pytest.approx(2 * 0.1 * 0.0024)
    assert measurement["surface_area_scale_interval_m2"] == pytest.approx(
        [0.0024 * 0.9**2, 0.0024 * 1.1**2]
    )
    assert measurement["provenance"]["calibration_verified"] is False


def test_independent_three_four_five_triangle_reference_and_duplicate_rejection() -> None:
    """A 3-4-5 right triangle has independently known area 6 m²."""
    from reefvision.schemas.spatial_mesh_preview_v14 import MeshPreviewRequest
    from reefvision.services.spatial_mesh_surface_v14 import preview_from_request

    vertices = [[0, 0, 0], [3, 0, 0], [0, 4, 0]]
    request = MeshPreviewRequest(
        vertices=vertices,
        faces=[[0, 1, 2]],
        meters_per_unit=1,
        calibration_method="ruler",
        calibration_evidence="Synthetic 3-4-5 triangle reference",
        relative_scale_uncertainty=0.1,
    )
    measurement = preview_from_request(request)
    assert measurement["surface_area_m2"] == pytest.approx(6.0)
    assert measurement["area_scale_uncertainty_m2"] == pytest.approx(1.2)
    assert measurement["surface_area_scale_interval_m2"] == pytest.approx([4.86, 7.26])
    assert measurement["provenance"]["calibration_verified"] is False

    with pytest.raises(ValueError, match="Duplicate triangle"):
        preview_from_request(request.model_copy(update={"faces": [[0, 1, 2], [2, 1, 0]]}))


@pytest.mark.parametrize("share_one_vertex", [False, True])
def test_independent_disconnected_triangles_are_edge_separate(
    share_one_vertex: bool,
) -> None:
    """Vertex contact alone cannot merge two 6 m² surface patches."""
    from reefvision.schemas.spatial_mesh_preview_v14 import MeshPreviewRequest
    from reefvision.services.spatial_mesh_surface_v14 import preview_from_request

    vertices = [
        [0, 0, 0],
        [3, 0, 0],
        [0, 4, 0],
        [10, 0, 0],
        [13, 0, 0],
        [10, 4, 0],
    ]
    if share_one_vertex:
        vertices[3:] = [[0, 0, 0], [-3, 0, 0], [0, -4, 0]]
    measurement = preview_from_request(
        MeshPreviewRequest(
            vertices=vertices,
            faces=[[0, 1, 2], [3, 4, 5]],
            meters_per_unit=1,
            calibration_method="ruler",
            calibration_evidence="Two independent synthetic 3-4-5 triangles",
        )
    )
    assert measurement["surface_area_m2"] == pytest.approx(12.0)
    assert measurement["edge_connected_patch_count"] == 2
    assert measurement["edge_connected_patch_face_counts"] == [1, 1]
    assert measurement["enclosed_volume_m3"] is None
    assert measurement["provenance"]["calibration_verified"] is False


def test_unreferenced_vertices_do_not_inflate_calibrated_mesh_extent() -> None:
    """Orphan import vertices must not change measured coral dimensions or camera fit."""
    from reefvision.schemas.spatial_mesh_preview_v14 import MeshPreviewRequest
    from reefvision.services.spatial_mesh_surface_v14 import preview_from_request

    request = MeshPreviewRequest(
        vertices=[[0, 0, 0], [3, 0, 0], [0, 4, 0]],
        faces=[[0, 1, 2]],
        meters_per_unit=0.5,
        calibration_method="ruler",
        calibration_evidence="Synthetic reference; calibration not independently verified",
    )
    baseline = preview_from_request(request)
    orphan = preview_from_request(
        request.model_copy(update={"vertices": [*request.vertices, [100000, -100000, 99999]]})
    )
    assert baseline["surface_area_m2"] == pytest.approx(1.5)
    assert orphan["surface_area_m2"] == pytest.approx(baseline["surface_area_m2"])
    assert orphan["axis_aligned_bounding_box_diagonal_m"] == pytest.approx(
        baseline["axis_aligned_bounding_box_diagonal_m"]
    )
    assert orphan["preview_camera_target_in_source_frame_m"] == pytest.approx(
        baseline["preview_camera_target_in_source_frame_m"]
    )
    assert orphan["preview_camera_radius_m"] == pytest.approx(baseline["preview_camera_radius_m"])
    assert orphan["unreferenced_vertex_count"] == 1
    assert orphan["provenance"]["calibration_verified"] is False
