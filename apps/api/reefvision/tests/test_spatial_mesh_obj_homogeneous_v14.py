"""OBJ homogeneous-coordinate and vertex-color scientific import regressions."""

from __future__ import annotations

import pytest

from reefvision.services.spatial_mesh_obj_v14 import parse_obj_triangles
from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview


def test_homogeneous_obj_vertices_are_normalized_before_calibration() -> None:
    text = "v 0 0 0 2\nv 4 0 0 2\nv 0 6 0 2\nf 1 2 3\n"
    vertices, faces = parse_obj_triangles(text)
    assert vertices == [[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 3.0, 0.0]]
    result = measure_mesh_preview(
        vertices=vertices,
        faces=faces,
        meters_per_unit=0.01,
        calibration_method="ruler",
        calibration_evidence="Provisional control",
    )
    assert result["surface_area_m2"] == pytest.approx(0.0003)
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert result["provenance"]["calibration_verified"] is False


def test_optional_rgb_and_weighted_rgb_vertices_are_accepted() -> None:
    plain = "v 0 0 0 0.2 0.3 0.4\nv 1 0 0 0.2 0.3 0.4\nv 0 1 0 0.2 0.3 0.4\nf 1 2 3\n"
    weighted = "v 0 0 0 2 0.2 0.3 0.4\nv 2 0 0 2 0.2 0.3 0.4\nv 0 2 0 2 0.2 0.3 0.4\nf 1 2 3\n"
    assert parse_obj_triangles(plain) == parse_obj_triangles(weighted)


@pytest.mark.parametrize(
    "vertex",
    [
        "v 0 0 0 0",
        "v 0 0 0 nan",
        "v 0 0 0 1 0",
        "v 0 0 0 1 0 0 0 0",
        "v 0 0 0 1 nan 0 0",
    ],
)
def test_invalid_homogeneous_or_color_layout_is_rejected(vertex: str) -> None:
    text = f"{vertex}\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"
    with pytest.raises(ValueError):
        parse_obj_triangles(text)
