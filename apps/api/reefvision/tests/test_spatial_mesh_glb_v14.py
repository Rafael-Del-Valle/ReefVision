"""Bounded GLB 2.0 parser regressions."""

from __future__ import annotations

import base64
import json
import struct

import pytest

from reefvision.services.spatial_mesh_glb_v14 import parse_glb_triangles


def make_glb(*, translated: bool = False, invalid_selector: str | None = None) -> str:
    binary = struct.pack("<9f3H", 0, 0, 0, 2, 0, 0, 0, 3, 0, 0, 1, 2)
    doc = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 36},
            {"buffer": 0, "byteOffset": 36, "byteLength": 6},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5123, "count": 3, "type": "SCALAR"},
        ],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        "nodes": [{"mesh": 0}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
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
    json_bytes = json.dumps(doc).encode()
    json_bytes += b" " * (-len(json_bytes) % 4)
    binary += b"\x00" * (-len(binary) % 4)
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
