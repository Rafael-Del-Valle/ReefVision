"""Independent reference for triangulation-independent coral surface measurement."""

from math import sqrt

import pytest

from reefvision.schemas.spatial_mesh_preview_v14 import MeshPreviewRequest
from reefvision.services.spatial_mesh_surface_v14 import preview_from_request


def test_planar_square_retriangulation_preserves_calibrated_area_and_extent() -> None:
    """Adding a center vertex changes facet counts, not physical coral surface area."""
    vertices = [[0, 0, 0], [2, 0, 0], [2, 2, 0], [0, 2, 0]]
    request = MeshPreviewRequest(
        vertices=vertices,
        faces=[[0, 1, 2], [0, 2, 3]],
        meters_per_unit=0.5,
        calibration_method="ruler",
        calibration_evidence="Synthetic 2-by-2 planar square; no independent scale review",
        relative_scale_uncertainty=0.1,
    )
    coarse = preview_from_request(request)
    refined = preview_from_request(
        request.model_copy(
            update={
                "vertices": [*vertices, [1, 1, 0]],
                "faces": [[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4]],
            }
        )
    )
    for measurement in (coarse, refined):
        assert measurement["surface_area_m2"] == pytest.approx(1.0)
        assert measurement["axis_aligned_bounding_box_diagonal_m"] == pytest.approx(sqrt(2))
        assert measurement["area_scale_uncertainty_m2"] == pytest.approx(0.2)
        assert measurement["surface_area_scale_interval_m2"] == pytest.approx([0.81, 1.21])
        assert measurement["edge_connected_patch_count"] == 1
        assert measurement["enclosed_volume_m3"] is None
        # A tessellation change cannot create biological boundary growth.
        assert measurement["boundary_edge_length_m"] == pytest.approx(4.0)
        assert measurement["boundary_loop_count"] == 1
        assert measurement["boundary_loop_perimeters_m"] == pytest.approx([4.0])
        assert measurement["boundary_loop_perimeter_scale_intervals_m"][0] == pytest.approx(
            [3.6, 4.4]
        )
        assert measurement["provenance"]["calibration_verified"] is False
    # Linear boundary metrics must scale linearly, unlike quadratic area.
    doubled = preview_from_request(request.model_copy(update={"meters_per_unit": 1.0}))
    assert doubled["boundary_edge_length_m"] == pytest.approx(8.0)
    assert doubled["boundary_loop_perimeters_m"] == pytest.approx([8.0])
    assert doubled["boundary_loop_perimeter_scale_intervals_m"][0] == pytest.approx([7.2, 8.8])
    assert doubled["surface_area_m2"] == pytest.approx(4.0)
    assert doubled["provenance"]["calibration_verified"] is False
    assert coarse["preview_face_count"] == 2
    assert refined["preview_face_count"] == 4


def test_disconnected_planar_patches_have_additive_area_without_false_volume() -> None:
    """Separate open coral patches must not be mistaken for one closed solid."""
    request = MeshPreviewRequest(
        vertices=[
            [0, 0, 0],
            [2, 0, 0],
            [0, 2, 0],
            [10, 0, 0],
            [12, 0, 0],
            [10, 2, 0],
        ],
        faces=[[0, 1, 2], [3, 4, 5]],
        meters_per_unit=0.5,
        calibration_method="ruler",
        calibration_evidence="Synthetic separated triangles; not independently verified",
        relative_scale_uncertainty=0.1,
    )
    result = preview_from_request(request)
    assert result["surface_area_m2"] == pytest.approx(1.0)
    assert result["area_scale_uncertainty_m2"] == pytest.approx(0.2)
    assert result["surface_area_scale_interval_m2"] == pytest.approx([0.81, 1.21])
    assert result["edge_connected_patch_count"] == 2
    assert result["preview_face_count"] == 2
    assert result["enclosed_volume_m3"] is None
    assert result["provenance"]["calibration_verified"] is False


def test_planar_boundary_perimeter_is_translation_invariant() -> None:
    """Changing a reconstruction origin must not imply coral boundary growth."""
    vertices = [[0, 0, 0], [2, 0, 0], [2, 2, 0], [0, 2, 0]]
    request = MeshPreviewRequest(
        vertices=vertices,
        faces=[[0, 1, 2], [0, 2, 3]],
        meters_per_unit=0.5,
        calibration_method="ruler",
        calibration_evidence="Synthetic translated planar surface; not independently verified",
        relative_scale_uncertainty=0.1,
    )
    original = preview_from_request(request)
    translated = preview_from_request(
        request.model_copy(
            update={"vertices": [[x + 1000, y - 2000, z + 3000] for x, y, z in vertices]}
        )
    )
    for key in (
        "surface_area_m2",
        "boundary_edge_length_m",
        "boundary_loop_count",
        "boundary_loop_perimeters_m",
        "edge_connected_patch_count",
    ):
        assert translated[key] == pytest.approx(original[key])
    assert translated["boundary_loop_perimeter_scale_intervals_m"][0] == pytest.approx(
        original["boundary_loop_perimeter_scale_intervals_m"][0]
    )
    assert translated["boundary_edge_length_m"] == pytest.approx(4.0)
    assert translated["provenance"]["calibration_verified"] is False


def test_closed_tetrahedron_volume_scales_cubically_without_verified_calibration() -> None:
    """Closed synthetic geometry must obey cubic volume and quadratic area scaling."""
    request = MeshPreviewRequest(
        vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
        faces=[[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]],
        meters_per_unit=1.0,
        calibration_method="ruler",
        calibration_evidence="Synthetic tetrahedron; scale has no independent review",
        relative_scale_uncertainty=0.1,
    )
    original = preview_from_request(request)
    doubled = preview_from_request(request.model_copy(update={"meters_per_unit": 2.0}))
    assert original["surface_area_m2"] == pytest.approx((3 + sqrt(3)) / 2)
    assert original["enclosed_volume_m3"] == pytest.approx(1 / 6)
    assert doubled["surface_area_m2"] == pytest.approx(4 * original["surface_area_m2"])
    assert doubled["enclosed_volume_m3"] == pytest.approx(8 * original["enclosed_volume_m3"])
    for measurement in (original, doubled):
        volume = measurement["enclosed_volume_m3"]
        assert measurement["boundary_edge_length_m"] == pytest.approx(0)
        assert measurement["edge_connected_patch_count"] == 1
        assert measurement["enclosed_volume_scale_interval_m3"] == pytest.approx(
            [volume * 0.9**3, volume * 1.1**3]
        )
        assert measurement["provenance"]["calibration_verified"] is False


def test_closed_tetrahedron_translation_preserves_volume_and_scale_interval() -> None:
    """Moving a watertight reconstruction cannot create apparent volume growth."""
    vertices = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]]
    request = MeshPreviewRequest(
        vertices=vertices,
        faces=[[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]],
        meters_per_unit=0.5,
        calibration_method="ruler",
        calibration_evidence="Synthetic translated tetrahedron; not independently verified",
        relative_scale_uncertainty=0.1,
    )
    original = preview_from_request(request)
    translated = preview_from_request(
        request.model_copy(
            update={"vertices": [[x + 100, y - 200, z + 300] for x, y, z in vertices]}
        )
    )
    assert original["enclosed_volume_m3"] == pytest.approx(1 / 48)
    assert translated["enclosed_volume_m3"] == pytest.approx(original["enclosed_volume_m3"])
    assert translated["surface_area_m2"] == pytest.approx(original["surface_area_m2"])
    assert translated["enclosed_volume_scale_interval_m3"] == pytest.approx(
        original["enclosed_volume_scale_interval_m3"]
    )
    assert translated["boundary_edge_length_m"] == pytest.approx(0)
    assert translated["provenance"]["calibration_verified"] is False


def test_open_surface_reversed_winding_preserves_area_but_not_false_volume() -> None:
    """Reversing triangle winding must not change an open coral patch's area."""
    request = MeshPreviewRequest(
        vertices=[[0, 0, 0], [2, 0, 0], [2, 2, 0], [0, 2, 0]],
        faces=[[0, 1, 2], [0, 2, 3]],
        meters_per_unit=0.5,
        calibration_method="ruler",
        calibration_evidence="Synthetic open surface; no independent calibration review",
        relative_scale_uncertainty=0.1,
    )
    forward = preview_from_request(request)
    reversed_faces = preview_from_request(
        request.model_copy(update={"faces": [[2, 1, 0], [3, 2, 0]]})
    )
    for result in (forward, reversed_faces):
        assert result["surface_area_m2"] == pytest.approx(1.0)
        assert result["boundary_edge_length_m"] == pytest.approx(4.0)
        assert result["enclosed_volume_m3"] is None
        assert result["provenance"]["calibration_verified"] is False
    assert reversed_faces["surface_area_scale_interval_m2"] == pytest.approx(
        forward["surface_area_scale_interval_m2"]
    )
