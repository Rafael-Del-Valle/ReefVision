"""Cross-format reproducibility check for the 1.4 provisional mesh preview."""

from __future__ import annotations

import pytest

from reefvision.schemas.spatial_mesh_preview_v14 import MeshPreviewRequest
from reefvision.services.spatial_mesh_surface_v14 import preview_from_request

COMMON = {
    "meters_per_unit": 0.01,
    "calibration_method": "ruler",
    "calibration_evidence": "Provisional scale target",
}
OBJ = "v 0 0 0\nv 2 0 0\nv 0 3 0\nf 1 2 3\n"
PLY = (
    "ply\nformat ascii 1.0\nelement vertex 3\n"
    "property float x\nproperty float y\nproperty float z\n"
    "element face 1\nproperty list uchar int vertex_indices\n"
    "end_header\n0 0 0\n2 0 0\n0 3 0\n3 0 1 2\n"
)


def test_obj_and_ply_share_calibrated_geometry_but_not_source_type() -> None:
    obj = preview_from_request(MeshPreviewRequest(**COMMON, obj_text=OBJ))
    ply = preview_from_request(MeshPreviewRequest(**COMMON, ply_text=PLY))
    assert obj["surface_area_m2"] == pytest.approx(0.0003)
    assert obj["surface_area_m2"] == pytest.approx(ply["surface_area_m2"])
    assert obj["provenance"]["geometry_sha256"] == ply["provenance"]["geometry_sha256"]
    assert obj["provenance"]["source_format"] == "obj"
    assert ply["provenance"]["source_format"] == "ply_ascii"
    assert obj["measurement_status"] == "caller_supplied_unverified"
    assert ply["measurement_status"] == "caller_supplied_unverified"
