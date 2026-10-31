"""OBJ homogeneous-coordinate and vertex-color scientific import regressions."""

from __future__ import annotations

import pytest

from reefvision.schemas.spatial_mesh_preview_v14 import MeshPreviewRequest
from reefvision.services.spatial_mesh_obj_v14 import parse_obj_triangles
from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview, preview_from_request


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


def test_inline_obj_comments_keep_geometry_but_change_byte_exact_source_identity() -> None:
    clean = "v 0 0 0\nv 2 0 0\nv 0 3 0\nf 1 2 3\n"
    commented = (
        "# Local reconstruction export\n"
        "v 0 0 0 # origin\n"
        "v 2 0 0 # x control\n"
        "v 0 3 0 # y control\n"
        "f 1/1/1 2/2/2 3/3/3 # triangle\n"
    )
    common = {
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Provisional scale control",
        "relative_scale_uncertainty": 0.05,
    }
    direct = preview_from_request(MeshPreviewRequest(obj_text=clean, **common))
    annotated = preview_from_request(MeshPreviewRequest(obj_text=commented, **common))
    assert annotated["surface_area_m2"] == pytest.approx(0.0003)
    assert annotated["surface_area_m2"] == direct["surface_area_m2"]
    assert annotated["surface_area_scale_interval_m2"] == direct["surface_area_scale_interval_m2"]
    assert annotated["provenance"]["geometry_sha256"] == direct["provenance"]["geometry_sha256"]
    assert (
        annotated["provenance"]["source_payload_sha256"]
        != direct["provenance"]["source_payload_sha256"]
    )
    assert annotated["provenance"]["source_payload_size_bytes"] == len(commented.encode())
    assert annotated["provenance"]["calibration_verified"] is False


@pytest.mark.parametrize(
    "invalid",
    ["v 0 0 0 extra # trailing note", "f 1 2 3 4 # polygon"],
)
def test_inline_obj_comments_do_not_hide_malformed_geometry(invalid: str) -> None:
    text = f"v 0 0 0\nv 2 0 0\nv 0 3 0\n{invalid}\nf 1 2 3\n"
    with pytest.raises(ValueError):
        parse_obj_triangles(text)


@pytest.mark.parametrize(
    "face",
    [
        "f 1 2 3",
        "f 1/2 2/3 3/4",
        "f 1//2 2//3 3//4",
        "f 1/2/3 2/3/4 3/4/5",
        "f -3/-3/-3 -2/-2/-2 -1/-1/-1",
    ],
)
def test_supported_obj_face_reference_forms_preserve_geometry(face: str) -> None:
    text = f"v 0 0 0\nv 2 0 0\nv 0 3 0\n{face}\n"
    vertices, faces = parse_obj_triangles(text)
    assert vertices == [[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 3.0, 0.0]]
    assert faces == [[0, 1, 2]]


@pytest.mark.parametrize(
    "face",
    [
        "f 1/ 2 3",
        "f 1// 2 3",
        "f 1/2/ 2 3",
        "f 1/2/3/4 2 3",
        "f 1//2/3 2 3",
        "f 1/a 2 3",
        "f 1//a 2 3",
        "f 1/0 2 3",
        "f 1//0 2 3",
        "f 1_0 2 3",
        "f \\u0661 2 3",
    ],
)
def test_malformed_obj_face_references_are_not_silently_measured(face: str) -> None:
    text = f"v 0 0 0\nv 2 0 0\nv 0 3 0\n{face}\n"
    with pytest.raises(ValueError, match="OBJ line 4:"):
        parse_obj_triangles(text)
