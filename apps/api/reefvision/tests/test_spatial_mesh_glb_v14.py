"""Bounded GLB 2.0 parser regressions."""

from __future__ import annotations

import base64
import json
import struct

import pytest

from reefvision.services.spatial_mesh_glb_v14 import parse_glb_triangles


def make_glb(
    *,
    translated: bool = False,
    invalid_selector: str | None = None,
    explicit_canonical: bool = False,
    explicit_targets: bool = False,
    nonindexed_vertices: int | None = None,
    unsigned_byte_indices: bool = False,
) -> str:
    positions = struct.pack("<9f", 0, 0, 0, 2, 0, 0, 0, 3, 0)
    binary = positions + (
        struct.pack("<3B", 0, 1, 2)
        if unsigned_byte_indices
        else struct.pack("<3H", 0, 1, 2)
    )
    doc = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 36},
            {"buffer": 0, "byteOffset": 36, "byteLength": 3 if unsigned_byte_indices else 6},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
            {
                "bufferView": 1,
                "componentType": 5121 if unsigned_byte_indices else 5123,
                "count": 3,
                "type": "SCALAR",
            },
        ],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        "nodes": [{"mesh": 0}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    if nonindexed_vertices is not None:
        if nonindexed_vertices not in (3, 4):
            raise ValueError("Test fixture supports three or four vertices")
        positions = (0.0, 0.0, 0.0, 2.0, 0.0, 0.0, 0.0, 3.0, 0.0, 0.0, 0.0, 1.0)
        values = positions[: 3 * nonindexed_vertices]
        binary = struct.pack(f"<{len(values)}f", *values)
        doc["buffers"][0]["byteLength"] = len(binary)
        doc["bufferViews"] = [{"buffer": 0, "byteOffset": 0, "byteLength": len(binary)}]
        doc["accessors"] = [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": nonindexed_vertices,
                "type": "VEC3",
            }
        ]
        del doc["meshes"][0]["primitives"][0]["indices"]
    if invalid_selector == "byte_index_oob" and unsigned_byte_indices:
        binary = binary[:-1] + b"\x03"
    if translated:
        doc["nodes"] = [{"mesh": 0, "translation": [1, 0, 0]}]
    if invalid_selector == "scene":
        doc["scene"] = False
    elif invalid_selector == "mesh":
        doc["nodes"][0]["mesh"] = False
    elif invalid_selector == "nodes":
        doc["scenes"][0]["nodes"] = [False]
    elif invalid_selector == "buffer":
        doc["bufferViews"][0]["buffer"] = False
    elif invalid_selector == "mode_float":
        doc["meshes"][0]["primitives"][0]["mode"] = 4.0
    elif invalid_selector == "position_component_float":
        doc["accessors"][0]["componentType"] = 5126.0
    elif invalid_selector == "index_component_float":
        doc["accessors"][1]["componentType"] = 5123.0
    elif invalid_selector == "normalized_integer":
        doc["accessors"][0]["normalized"] = 0
    elif invalid_selector == "stride_float":
        doc["bufferViews"][0]["byteStride"] = 12.0
    elif invalid_selector == "json_nan":
        doc["extras"] = {"nonfinite": float("nan")}
    elif invalid_selector == "json_infinity":
        doc["extras"] = {"nonfinite": float("inf")}
    elif invalid_selector == "json_negative_infinity":
        doc["extras"] = {"nonfinite": float("-inf")}
    if explicit_targets:
        doc["bufferViews"][0]["target"] = 34962
        doc["bufferViews"][1]["target"] = 34963
    if invalid_selector == "position_target_index":
        doc["bufferViews"][0]["target"] = 34963
    elif invalid_selector == "index_target_vertex":
        doc["bufferViews"][1]["target"] = 34962
    elif invalid_selector == "target_float":
        doc["bufferViews"][0]["target"] = 34962.0
    elif invalid_selector == "target_boolean":
        doc["bufferViews"][0]["target"] = True
    if explicit_canonical:
        doc["meshes"][0]["primitives"][0]["mode"] = 4
        doc["accessors"][0]["normalized"] = False
        doc["bufferViews"][0]["byteStride"] = 12
    json_bytes = json.dumps(doc).encode()
    json_bytes += b" " * (-len(json_bytes) % 4)
    binary += b"\x00" * (-len(binary) % 4)
    if invalid_selector == "nonzero_bin_padding":
        binary = binary[:-1] + b"\x01"
    length = 12 + 8 + len(json_bytes) + 8 + len(binary)
    glb = (
        struct.pack("<4sII", b"glTF", 2, length)
        + struct.pack("<I4s", len(json_bytes), b"JSON")
        + json_bytes
        + struct.pack("<I4s", len(binary), b"BIN\x00")
        + binary
    )
    return base64.b64encode(glb).decode()


def test_single_glb_triangle() -> None:
    vertices, faces = parse_glb_triangles(make_glb())
    assert vertices == [[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 3.0, 0.0]]
    assert faces == [[0, 1, 2]]


def test_rejects_scene_transforms() -> None:
    with pytest.raises(ValueError, match="transforms"):
        parse_glb_triangles(make_glb(translated=True))


def test_rejects_invalid_base64() -> None:
    with pytest.raises(ValueError, match="base64"):
        parse_glb_triangles("invalid%%")


@pytest.mark.parametrize("invalid_selector", ["scene", "mesh", "nodes", "buffer"])
def test_rejects_boolean_glb_indices(invalid_selector: str) -> None:
    """JSON booleans must not masquerade as zero-valued glTF indices."""
    with pytest.raises(ValueError, match="index"):
        parse_glb_triangles(make_glb(invalid_selector=invalid_selector))


@pytest.mark.parametrize(
    "invalid_selector",
    [
        "mode_float",
        "position_component_float",
        "index_component_float",
        "normalized_integer",
        "stride_float",
    ],
)
def test_rejects_noncanonical_glb_numeric_geometry_metadata(invalid_selector: str) -> None:
    """JSON floats and integers must not masquerade as glTF schema types."""
    with pytest.raises(ValueError):
        parse_glb_triangles(make_glb(invalid_selector=invalid_selector))


def test_explicit_canonical_glb_numeric_metadata_preserves_geometry() -> None:
    """Valid explicit JSON integer/boolean metadata must remain supported."""
    assert parse_glb_triangles(make_glb(explicit_canonical=True)) == parse_glb_triangles(make_glb())


@pytest.mark.parametrize(
    "invalid_selector",
    ["json_nan", "json_infinity", "json_negative_infinity", "nonzero_bin_padding"],
)
def test_rejects_nonstandard_json_and_nonzero_binary_padding(invalid_selector: str) -> None:
    """Nonfinite JSON extensions and nonzero BIN padding are not valid glTF 2.0."""
    with pytest.raises(ValueError, match=r"nonfinite|padding"):
        parse_glb_triangles(make_glb(invalid_selector=invalid_selector))


def test_nonindexed_triangles_match_indexed_geometry() -> None:
    """Non-indexed glTF TRIANGLES have consecutive, independent vertex triplets."""
    assert parse_glb_triangles(make_glb(nonindexed_vertices=3)) == parse_glb_triangles(make_glb())


def test_rejects_incomplete_nonindexed_triangle() -> None:
    with pytest.raises(ValueError, match="complete vertex triplets"):
        parse_glb_triangles(make_glb(nonindexed_vertices=4))


def test_explicit_glb_buffer_view_targets_preserve_geometry() -> None:
    """Canonical vertex and index targets do not alter measured geometry."""
    assert parse_glb_triangles(make_glb(explicit_targets=True)) == parse_glb_triangles(make_glb())


@pytest.mark.parametrize(
    "invalid_selector",
    ["position_target_index", "index_target_vertex", "target_float", "target_boolean"],
)
def test_rejects_incompatible_glb_buffer_view_targets(invalid_selector: str) -> None:
    """An explicitly declared buffer target must match its accessor role."""
    with pytest.raises(ValueError, match="target"):
        parse_glb_triangles(make_glb(invalid_selector=invalid_selector))


def test_unsigned_byte_indices_match_unsigned_short_geometry() -> None:
    """glTF 2.0 permits UNSIGNED_BYTE index accessors (componentType 5121)."""
    assert parse_glb_triangles(make_glb(unsigned_byte_indices=True)) == parse_glb_triangles(
        make_glb()
    )


def test_rejects_out_of_bounds_unsigned_byte_indices() -> None:
    with pytest.raises(ValueError, match="index out of bounds"):
        parse_glb_triangles(
            make_glb(unsigned_byte_indices=True, invalid_selector="byte_index_oob")
        )
