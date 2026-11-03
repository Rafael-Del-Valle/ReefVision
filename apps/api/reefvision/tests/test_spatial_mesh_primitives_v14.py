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
    assert measurement["area_scale_uncertainty_m2"] == pytest.approx(
        [0.0024 * 0.9**2, 0.0024 * 1.1**2]
    )
    assert measurement["provenance"]["calibration_verified"] is False
