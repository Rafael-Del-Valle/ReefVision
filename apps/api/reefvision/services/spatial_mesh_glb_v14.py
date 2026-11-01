"""Bounded GLB 2.0 parser for provisional, untransformed triangle previews."""

from __future__ import annotations

import base64
import binascii
import json
import struct
from math import isclose, isfinite
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


def _reject_nonfinite_json_constant(value: str) -> None:
    """Reject Python JSON decoder extensions forbidden by glTF 2.0 JSON."""
    raise ValueError(f"GLB JSON contains nonfinite constant: {value}")


def _finite_json_float(value: str) -> float:
    """Reject JSON exponent overflow, including in otherwise ignored metadata."""
    parsed = float(value)
    if not isfinite(parsed):
        raise ValueError("GLB JSON contains nonfinite number")
    return parsed


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
    """Decode one embedded TRIANGLES primitive without applying scene transforms.

    External buffers, compression, hierarchy, transforms, and sparse accessors
    are rejected. Bounded interleaved POSITION data are supported.
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
            json.loads(
                chunks[0][1].decode("utf-8"),
                object_pairs_hook=_unique_keys,
                parse_constant=_reject_nonfinite_json_constant,
                parse_float=_finite_json_float,
            ),
            "root",
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Invalid GLB JSON") from exc
    asset = _as_object(doc.get("asset"), "asset")
    if asset.get("version") != "2.0":
        raise ValueError("GLB asset must declare version 2.0")
    if "minVersion" in asset and asset["minVersion"] != "2.0":
        raise ValueError("GLB asset minimum version must be 2.0")
    if doc.get("extensionsUsed") or doc.get("extensionsRequired"):
        raise ValueError("GLB extensions are unsupported")
    # An animated node can change the measured geometry after the bind pose.
    # This bounded preview has no animation timeline or skinning evaluation.
    if "animations" in doc or "skins" in doc:
        raise ValueError("GLB animations and skinning are unsupported")
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
    if any(binary[buffer_length:]):
        raise ValueError("GLB binary padding must be zero")
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
        or any(key in node for key in ("children", "skin", "weights"))
    ):
        raise ValueError("GLB scene transforms, hierarchy and morph weights are unsupported")
    # Some exporters write a column-major 4x4 identity matrix rather than
    # omitting transforms. Accept only that exact no-op, never silently
    # measure a translated, rotated, scaled, or malformed scene.
    if "matrix" in node:
        if any(key in node for key in ("translation", "rotation", "scale")):
            raise ValueError("GLB matrix and TRS transforms cannot be combined")
        matrix = _as_list(node["matrix"], "node matrix")
        identity_matrix = tuple(1.0 if index % 5 == 0 else 0.0 for index in range(16))
        if len(matrix) != 16 or any(
            type(value) not in (int, float)
            or not -1_000_000_000 <= value <= 1_000_000_000
            or not isfinite(value)
            or value != expected
            for value, expected in zip(matrix, identity_matrix, strict=True)
        ):
            raise ValueError("GLB nonidentity or invalid scene transforms are unsupported")
    # Explicit identity TRS values are common in otherwise untransformed GLB
    # exports. Accept only exact identities; never silently apply a transform
    # to a specimen's calibrated geometry.
    for name, identity in (
        ("translation", (0.0, 0.0, 0.0)),
        ("rotation", (0.0, 0.0, 0.0, 1.0)),
        ("scale", (1.0, 1.0, 1.0)),
    ):
        if name not in node:
            continue
        values = _as_list(node[name], f"node {name}")
        if len(values) != len(identity) or any(
            type(value) not in (int, float) or not isfinite(value) or value != expected
            for value, expected in zip(values, identity, strict=True)
        ):
            raise ValueError("GLB nonidentity or invalid scene transforms are unsupported")
    mesh = _as_object(meshes[0], "mesh")
    if "weights" in mesh:
        raise ValueError("GLB morph weights are unsupported")
    primitives = _as_list(mesh.get("primitives"), "primitives")
    if len(primitives) != 1:
        raise ValueError("GLB preview requires one primitive")
    primitive = _as_object(primitives[0], "primitive")
    attributes = _as_object(primitive.get("attributes"), "attributes")
    if (
        type(primitive.get("mode", 4)) is not int
        or primitive.get("mode", 4) != 4
        or "POSITION" not in attributes
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
            if type(component) is not int or component != 5126 or accessor.get("type") != "VEC3":
                raise ValueError("GLB positions require float32 VEC3")
            fmt, width, limit = "<fff", 12, MAX_VERTICES
        else:
            if (
                type(component) is not int
                or component not in (5121, 5123, 5125)
                or accessor.get("type") != "SCALAR"
            ):
                raise ValueError("GLB indices require unsigned 8/16/32-bit scalars")
            fmt, width = {5121: ("<B", 1), 5123: ("<H", 2), 5125: ("<I", 4)}[component]
            limit = 3 * MAX_FACES
        count = _as_int(accessor.get("count"), "accessor count", 1)
        if count > limit or (position and count < 3) or (not position and count % 3):
            raise ValueError("GLB accessor count is not a bounded triangle mesh")
        if "sparse" in accessor or (
            "normalized" in accessor
            and (type(accessor["normalized"]) is not bool or accessor["normalized"])
        ):
            raise ValueError("GLB sparse/normalized accessors are unsupported")
        view_index = _as_int(accessor.get("bufferView"), "bufferView index")
        if view_index >= len(views):
            raise ValueError("GLB bufferView index out of range")
        view = _as_object(views[view_index], "bufferView")
        # glTF bufferView targets are optional; when present they must match
        # the accessor's role. Never interpret index bytes as vertex data.
        expected_target = 34962 if position else 34963
        if "target" in view and (
            type(view["target"]) is not int or view["target"] != expected_target
        ):
            raise ValueError("GLB bufferView target conflicts with accessor role")
        if _as_int(view.get("buffer"), "buffer index") != 0:
            raise ValueError("GLB external buffer views are unsupported")
        stride = width
        if "byteStride" in view:
            if not position:
                raise ValueError("GLB strided index views are unsupported")
            candidate = view["byteStride"]
            if type(candidate) is not int or not 12 <= candidate <= 252 or candidate % 4:
                raise ValueError("GLB vertex byteStride must be 12-252, divisible by four")
            stride = candidate
        start = _as_int(view.get("byteOffset", 0), "view offset")
        size = _as_int(view.get("byteLength"), "view length")
        accessor_offset = _as_int(accessor.get("byteOffset", 0), "accessor offset")
        # glTF bufferView offsets are four-byte aligned. Accessor offsets
        # align to the component type (float32 positions: 4 bytes), not the
        # entire VEC3 element (12 bytes). A valid position view may start at
        # byte 4 without being a multiple of 12.
        component_width = 4 if position else width
        if (
            start + size > buffer_length
            or accessor_offset + (count - 1) * stride + width > size
            or (stride > width and accessor_offset % stride + width > stride)
            or start % 4
            or accessor_offset % component_width
        ):
            raise ValueError("GLB accessor exceeds or misaligns its buffer view")
        offset = start + accessor_offset
        return [struct.unpack_from(fmt, binary, offset + i * stride) for i in range(count)]

    vertices = [list(row) for row in read_accessor(attributes["POSITION"], position=True)]
    if any(not isfinite(v) or abs(v) > 1_000_000_000 for row in vertices for v in row):
        raise ValueError("GLB positions must be bounded and finite")
    # POSITION min/max are optional exporter metadata, not independent
    # calibration. When supplied, bind them to the actual decoded vertices.
    position_accessor = _as_object(accessors[attributes["POSITION"]], "position accessor")
    for field, reducer in (("min", min), ("max", max)):
        if field not in position_accessor:
            continue
        declared = _as_list(position_accessor[field], f"position {field}")
        if len(declared) != 3 or any(
            type(value) not in (int, float)
            or not -1_000_000_000 <= value <= 1_000_000_000
            or not isfinite(value)
            for value in declared
        ):
            raise ValueError("GLB position bounds require three bounded finite numbers")
        actual = [reducer(row[axis] for row in vertices) for axis in range(3)]
        if any(
            not isclose(value, expected, rel_tol=1e-6, abs_tol=1e-8)
            for value, expected in zip(declared, actual, strict=True)
        ):
            raise ValueError("GLB position bounds conflict with decoded geometry")
    if "indices" in primitive:
        indices = [int(row[0]) for row in read_accessor(primitive["indices"], position=False)]
        if any(index >= len(vertices) for index in indices):
            raise ValueError("GLB face index out of bounds")
        # Optional exporter min/max metadata must describe the actual decoded
        # index buffer. It is not independent evidence of mesh correctness.
        index_accessor = _as_object(accessors[primitive["indices"]], "index accessor")
        for field, reducer in (("min", min), ("max", max)):
            if field not in index_accessor:
                continue
            declared = _as_list(index_accessor[field], f"index {field}")
            expected = reducer(indices)
            if len(declared) != 1 or type(declared[0]) is not int or declared[0] != expected:
                raise ValueError("GLB index bounds conflict with decoded indices")
    else:
        # glTF TRIANGLES may omit indices; each consecutive vertex triplet
        # forms one independent face. Never infer a triangle strip or fan.
        if len(vertices) % 3 or len(vertices) // 3 > MAX_FACES:
            raise ValueError("GLB non-indexed TRIANGLES require complete vertex triplets")
        indices = list(range(len(vertices)))
    return vertices, [indices[i : i + 3] for i in range(0, len(indices), 3)]
