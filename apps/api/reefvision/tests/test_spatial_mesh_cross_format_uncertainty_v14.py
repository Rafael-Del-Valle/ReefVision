"""Cross-format calibration propagation regression for provisional 3D meshes."""

from __future__ import annotations

import pytest

from reefvision.schemas.spatial_mesh_preview_v14 import MeshPreviewRequest
from reefvision.services.spatial_mesh_surface_v14 import preview_from_request
from reefvision.tests.test_spatial_mesh_cross_format_v14 import COMMON, OBJ, PLY


def test_obj_ply_dimension_uncertainty_and_provenance_parity() -> None:
    options = {**COMMON, "relative_scale_uncertainty": 0.1}
    obj = preview_from_request(MeshPreviewRequest(**options, obj_text=OBJ))
    ply = preview_from_request(MeshPreviewRequest(**options, ply_text=PLY))
    assert obj["axis_aligned_dimensions_m"] == pytest.approx([0.02, 0.03, 0.0])
    assert ply["axis_aligned_dimensions_m"] == pytest.approx(obj["axis_aligned_dimensions_m"])
    assert obj["axis_aligned_dimension_scale_uncertainty_m"] == pytest.approx([0.002, 0.003, 0.0])
    assert ply["axis_aligned_dimension_scale_uncertainty_m"] == pytest.approx(
        obj["axis_aligned_dimension_scale_uncertainty_m"]
    )
    assert obj["area_scale_uncertainty_m2"] == pytest.approx(0.00006)
    assert ply["area_scale_uncertainty_m2"] == pytest.approx(obj["area_scale_uncertainty_m2"])
    assert obj["confidence_interval"] is None
    assert ply["confidence_interval"] is None
    assert obj["measurement_status"] == "caller_supplied_unverified"
    assert ply["measurement_status"] == "caller_supplied_unverified"
