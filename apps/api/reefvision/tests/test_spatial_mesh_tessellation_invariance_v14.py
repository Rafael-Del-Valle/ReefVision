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
        assert measurement["provenance"]["calibration_verified"] is False
    assert coarse["preview_face_count"] == 2
    assert refined["preview_face_count"] == 4
