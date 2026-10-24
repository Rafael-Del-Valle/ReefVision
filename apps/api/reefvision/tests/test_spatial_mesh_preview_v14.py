from __future__ import annotations

import pytest

from reefvision.services.spatial_mesh_obj_v14 import parse_obj_triangles
from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview

TRIANGLE = [[0, 0, 0], [2, 0, 0], [0, 3, 0]]
FACES = [[0, 1, 2]]


def preview(**changes):
    arguments = {
        "vertices": TRIANGLE,
        "faces": FACES,
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Measured control target; pending scientist review",
        "relative_scale_uncertainty": 0.05,
    }
    arguments.update(changes)
    return measure_mesh_preview(**arguments)


def test_calibrated_area_dimensions_and_uncertainty():
    result = preview()
    assert result["surface_area_m2"] == pytest.approx(0.0003)
    assert result["axis_aligned_dimensions_m"] == pytest.approx([0.02, 0.03, 0])
    assert result["area_scale_uncertainty_m2"] == pytest.approx(0.00003)
    assert result["axis_aligned_dimension_scale_uncertainty_m"] == pytest.approx(
        [0.001, 0.0015, 0.0]
    )
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert result["provenance"]["calibration_verified"] is False
    assert len(result["provenance"]["geometry_sha256"]) == 64
    assert "open_mesh_surface_not_enclosed" in result["qc_warnings"]


def test_obj_parser_supports_negative_indices_and_texture_fields():
    vertices, faces = parse_obj_triangles("v 0 0 0\nv 2 0 0\nv 0 3 0\nf -3/1/1 -2/2/1 -1/3/1\n")
    assert vertices == TRIANGLE
    assert faces == FACES
    assert preview(vertices=vertices, faces=faces)["surface_area_m2"] == pytest.approx(0.0003)


@pytest.mark.parametrize(
    "text",
    [
        "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 4",
        "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 0 1 2",
        "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3 3",
        "v nan 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3",
    ],
)
def test_obj_rejects_unsafe_or_ambiguous_geometry(text):
    with pytest.raises(ValueError):
        parse_obj_triangles(text)


@pytest.mark.parametrize(
    "changes",
    [
        {"meters_per_unit": 0},
        {"meters_per_unit": float("nan")},
        {"calibration_evidence": ""},
        {"relative_scale_uncertainty": -0.01},
        {"faces": [[0, 0, 1]]},
        {"faces": [[0, 1, 3]]},
        {"faces": [[0, 1, 2], [2, 0, 1]]},
        {"vertices": [[0, 0, 0], [1, float("inf"), 0], [0, 1, 0]]},
    ],
)
def test_invalid_measurement_inputs_rejected(changes):
    with pytest.raises(ValueError):
        preview(**changes)


def test_degenerate_faces_are_reported_not_silently_promoted():
    result = preview(vertices=[[0, 0, 0], [1, 1, 1], [2, 2, 2]])
    assert result["surface_area_m2"] == 0
    assert result["degenerate_face_count"] == 1
    assert "degenerate_triangles_present" in result["qc_warnings"]


def test_repeated_preview_is_deterministic():
    assert preview() == preview()
