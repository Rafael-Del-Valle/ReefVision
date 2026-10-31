"""Bounded GLB 2.0 parser for provisional, untransformed triangle previews."""

from __future__ import annotations

import base64
import binascii
import json
import struct
from math import isfinite
from typing import Any

from reefvision.services.spatial_mesh_obj_v14 import MAX_FACES, MAX_VERTICES

MAX_GLB_BYTES = 256_000


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate GLB JSON key")
        result[key] = value
    return result


def _as_object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"GLB {name} must be an object")
    return value


def _as_list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"GLB {name} must be an array")
    return value


def _as_int(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"GLB {name} must be an integer >= {minimum}")
    return value


def parse_glb_triangles(encoded: str) -> tuple[list[list[float]], list[list[int]]]:
    """Decode one embedded indexed TRIANGLES primitive without applying scene transforms.

    External buffers, compression, hierarchy, transforms, sparse accessors, and
    interleaved vertex data are rejected rather than measured incorrectly.
    """
    if not isinstance(encoded, str) or len(encoded) > 350_000:
        raise ValueError("GLB base64 exceeds preview bounds")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("GLB requires valid base64") from exc
    if not 20 <= len(raw) <= MAX_GLB_BYTES:
        raise ValueError("GLB binary exceeds preview bounds")
    magic, version, declared_length = struct.unpack_from("<4sII", raw)
    if magic != b"glTF" or version != 2 or declared_length != len(raw):
        raise ValueError("Invalid GLB 2.0 header")
    cursor = 12
    chunks: list[tuple[bytes, bytes]] = []
    while cursor < len(raw):
        if cursor + 8 > len(raw):
            raise ValueError("Truncated GLB chunk")
        length, kind = struct.unpack_from("<I4s", raw, cursor)
        cursor += 8
        if length % 4 or length > len(raw) - cursor:
            raise ValueError("Invalid GLB chunk length")
        chunks.append((kind, raw[cursor : cursor + length]))
        cursor += length
    if len(chunks) != 2 or [kind for kind, _ in chunks] != [b"JSON", b"BIN\x00"]:
        raise ValueError("GLB preview requires one JSON and one BIN chunk")
    try:
        doc = _as_object(
            json.loads(chunks[0][1].decode("utf-8"), object_pairs_hook=_unique_keys),
            "root",
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Invalid GLB JSON") from exc
    if _as_object(doc.get("asset"), "asset").get("version") != "2.0":
        raise ValueError("GLB asset must declare version 2.0")
    if doc.get("extensionsUsed") or doc.get("extensionsRequired"):
        raise ValueError("GLB extensions are unsupported")
    buffers = _as_list(doc.get("buffers"), "buffers")
    views = _as_list(doc.get("bufferViews"), "bufferViews")
    accessors = _as_list(doc.get("accessors"), "accessors")
    meshes = _as_list(doc.get("meshes"), "meshes")
    nodes = _as_list(doc.get("nodes"), "nodes")
    scenes = _as_list(doc.get("scenes"), "scenes")
    if len(buffers) != 1 or len(meshes) != 1 or len(nodes) != 1 or len(scenes) != 1:
        raise ValueError("GLB preview requires one buffer, mesh, node and scene")
    buffer = _as_object(buffers[0], "buffer")
    buffer_length = _as_int(buffer.get("byteLength"), "buffer length")
    binary = chunks[1][1]
    if "uri" in buffer or not buffer_length <= len(binary) <= buffer_length + 3:
        raise ValueError("GLB requires one embedded binary buffer")
    node = _as_object(nodes[0], "node")
    scene = _as_object(scenes[0], "scene")
    scene_index = _as_int(doc.get("scene"), "scene index")
    mesh_index = _as_int(node.get("mesh"), "node mesh index")
    scene_nodes = _as_list(scene.get("nodes"), "scene nodes")
    if (
        scene_index != 0
        or mesh_index != 0
        or len(scene_nodes) != 1
        or _as_int(scene_nodes[0], "scene node index") != 0
        or any(
            key in node
            for key in ("matrix", "translation", "rotation", "scale", "children", "skin")
        )
    ):
        raise ValueError("GLB scene transforms and hierarchy are unsupported")
    mesh = _as_object(meshes[0], "mesh")
    primitives = _as_list(mesh.get("primitives"), "primitives")
    if len(primitives) != 1:
        raise ValueError("GLB preview requires one primitive")
    primitive = _as_object(primitives[0], "primitive")
    attributes = _as_object(primitive.get("attributes"), "attributes")
    if (
        primitive.get("mode", 4) != 4
        or "POSITION" not in attributes
        or "indices" not in primitive
        or "targets" in primitive
        or "extensions" in primitive
    ):
        raise ValueError("GLB preview requires indexed TRIANGLES geometry")

    def read_accessor(index: Any, *, position: bool) -> list[tuple[Any, ...]]:
        accessor_index = _as_int(index, "accessor index")
        if accessor_index >= len(accessors):
            raise ValueError("GLB accessor index out of range")
        accessor = _as_object(accessors[accessor_index], "accessor")
        component = accessor.get("componentType")
        if position:
            if component != 5126 or accessor.get("type") != "VEC3":
                raise ValueError("GLB positions require float32 VEC3")
            fmt, width, limit = "<fff", 12, MAX_VERTICES
        else:
            if component not in (5123, 5125) or accessor.get("type") != "SCALAR":
                raise ValueError("GLB indices require unsigned 16/32-bit scalars")
            fmt, width = ("<H", 2) if component == 5123 else ("<I", 4)
            limit = 3 * MAX_FACES
        count = _as_int(accessor.get("count"), "accessor count", 1)
        if count > limit or (position and count < 3) or (not position and count % 3):
            raise ValueError("GLB accessor count is not a bounded triangle mesh")
        if "sparse" in accessor or accessor.get("normalized", False):
            raise ValueError("GLB sparse/normalized accessors are unsupported")
        view_index = _as_int(accessor.get("bufferView"), "bufferView index")
        if view_index >= len(views):
            raise ValueError("GLB bufferView index out of range")
        view = _as_object(views[view_index], "bufferView")
        if _as_int(view.get("buffer"), "buffer index") != 0 or (
            "byteStride" in view and view["byteStride"] != width
        ):
            raise ValueError("GLB strided or external views are unsupported")
        start = _as_int(view.get("byteOffset", 0), "view offset")
        size = _as_int(view.get("byteLength"), "view length")
        accessor_offset = _as_int(accessor.get("byteOffset", 0), "accessor offset")
        if (
            start + size > buffer_length
            or accessor_offset + count * width > size
            or (start + accessor_offset) % width
        ):
            raise ValueError("GLB accessor exceeds or misaligns its buffer view")
        offset = start + accessor_offset
        return [struct.unpack_from(fmt, binary, offset + i * width) for i in range(count)]

    vertices = [list(row) for row in read_accessor(attributes["POSITION"], position=True)]
    if any(not isfinite(v) or abs(v) > 1_000_000_000 for row in vertices for v in row):
        raise ValueError("GLB positions must be bounded and finite")
    indices = [int(row[0]) for row in read_accessor(primitive["indices"], position=False)]
    if any(index >= len(vertices) for index in indices):
        raise ValueError("GLB face index out of bounds")
    return vertices, [indices[i : i + 3] for i in range(0, len(indices), 3)]
