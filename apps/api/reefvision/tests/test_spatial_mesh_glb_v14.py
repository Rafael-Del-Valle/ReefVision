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
    explicit_min_version: bool = False,
    explicit_empty_extensions: bool = False,
    explicit_targets: bool = False,
    identity_transform: str | None = None,
    nonindexed_vertices: int | None = None,
    unsigned_byte_indices: bool = False,
    unsigned_int_indices: bool = False,
    position_offset: int = 0,
    position_stride: int | None = None,
    position_leading_bytes: int = 0,
    position_bounds: bool = False,
    index_bounds: bool = False,
) -> str:
    if invalid_selector == "misaligned_position_view":
        position_offset = 2
    if invalid_selector == "stride_too_small":
        position_stride = 8
    elif invalid_selector == "stride_unaligned":
        position_stride = 14
    elif invalid_selector == "stride_oversize":
        position_stride = 256
    elif invalid_selector == "stride_boolean":
        position_stride = True
    elif invalid_selector == "stride_truncated":
        position_stride = 16
    elif invalid_selector == "stride_overlap":
        position_stride = 16
        position_leading_bytes = 8
    positions = struct.pack("<9f", 0, 0, 0, 2, 0, 0, 0, 3, 0)
    if type(position_stride) is int and position_stride >= 12:
        positions = b"".join(
            b"\x00" * position_leading_bytes
            + positions[index : index + 12]
            + b"\x00" * max(0, position_stride - 12 - position_leading_bytes)
            for index in range(0, len(positions), 12)
        )
    position_size = len(positions)
    if unsigned_byte_indices and unsigned_int_indices:
        raise ValueError("Test fixture index widths are mutually exclusive")
    if unsigned_int_indices:
        index_bytes = struct.pack("<3I", 0, 1, 2)
        index_component_type = 5125
    elif unsigned_byte_indices:
        index_bytes = struct.pack("<3B", 0, 1, 2)
        index_component_type = 5121
    else:
        index_bytes = struct.pack("<3H", 0, 1, 2)
        index_component_type = 5123
    binary = b"\x00" * position_offset + positions + index_bytes
    doc = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": position_offset, "byteLength": position_size},
            {
                "buffer": 0,
                "byteOffset": position_offset + position_size,
                "byteLength": len(index_bytes),
            },
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
            {
                "bufferView": 1,
                "componentType": index_component_type,
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
        vertex_bytes = struct.pack(f"<{len(values)}f", *values)
        binary = b"\x00" * position_offset + vertex_bytes
        doc["buffers"][0]["byteLength"] = len(binary)
        doc["bufferViews"] = [
            {"buffer": 0, "byteOffset": position_offset, "byteLength": len(vertex_bytes)}
        ]
        doc["accessors"] = [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": nonindexed_vertices,
                "type": "VEC3",
            }
        ]
        del doc["meshes"][0]["primitives"][0]["indices"]
    if position_stride is not None:
        doc["bufferViews"][0]["byteStride"] = position_stride
    if position_leading_bytes:
        doc["accessors"][0]["byteOffset"] = position_leading_bytes
    if invalid_selector == "stride_truncated":
        doc["bufferViews"][0]["byteLength"] = 36
    if position_bounds:
        doc["accessors"][0]["min"] = [0.0, 0.0, 0.0]
        doc["accessors"][0]["max"] = [2.0, 3.0, 0.0]
    if invalid_selector == "bounds_short":
        doc["accessors"][0]["min"] = [0.0, 0.0]
    elif invalid_selector == "bounds_boolean":
        doc["accessors"][0]["max"] = [2.0, True, 0.0]
    elif invalid_selector == "bounds_nan":
        doc["accessors"][0]["min"] = [0.0, float("nan"), 0.0]
    elif invalid_selector == "bounds_mismatch":
        doc["accessors"][0]["max"] = [3.0, 3.0, 0.0]
    if index_bounds:
        doc["accessors"][1]["min"] = [0]
        doc["accessors"][1]["max"] = [2]
    if invalid_selector == "index_bounds_float":
        doc["accessors"][1]["max"] = [2.0]
    elif invalid_selector == "index_bounds_short":
        doc["accessors"][1]["min"] = [0, 1]
    elif invalid_selector == "index_bounds_boolean":
        doc["accessors"][1]["min"] = [False]
    elif invalid_selector == "index_bounds_mismatch":
        doc["accessors"][1]["max"] = [1]
    elif invalid_selector == "index_bounds_negative":
        doc["accessors"][1]["min"] = [-1]
    elif invalid_selector == "index_bounds_nan":
        doc["accessors"][1]["max"] = [float("nan")]
    elif invalid_selector == "index_bounds_huge":
        doc["accessors"][1]["max"] = [10**400]
    if invalid_selector == "byte_index_oob" and unsigned_byte_indices:
        binary = binary[:-1] + b"\x03"
    if invalid_selector == "dword_index_oob" and unsigned_int_indices:
        binary = binary[:-4] + struct.pack("<I", 3)
    if invalid_selector == "asset_min_version_future":
        doc["asset"]["minVersion"] = "2.1"
    elif invalid_selector == "asset_min_version_numeric":
        doc["asset"]["minVersion"] = 2.0
    elif invalid_selector == "asset_min_version_boolean":
        doc["asset"]["minVersion"] = True
    if identity_transform is not None:
        identities = {
            "translation": [0, 0, 0],
            "rotation": [0, 0, 0, 1],
            "scale": [1, 1, 1],
            "matrix": [int(index % 5 == 0) for index in range(16)],
        }
        doc["nodes"][0][identity_transform] = identities[identity_transform]
    if translated:
        doc["nodes"] = [{"mesh": 0, "translation": [1, 0, 0]}]
    if invalid_selector == "nonidentity_scale":
        doc["nodes"][0]["scale"] = [1, 2, 1]
    elif invalid_selector == "nonidentity_rotation":
        doc["nodes"][0]["rotation"] = [0, 0, 1, 0]
    elif invalid_selector == "boolean_identity_translation":
        doc["nodes"][0]["translation"] = [0, False, 0]
    elif invalid_selector == "short_identity_translation":
        doc["nodes"][0]["translation"] = [0, 0]
    if invalid_selector in {
        "nonidentity_matrix",
        "boolean_identity_matrix",
        "short_identity_matrix",
        "mixed_matrix_trs",
        "huge_identity_matrix",
    }:
        doc["nodes"][0]["matrix"] = [int(index % 5 == 0) for index in range(16)]
        matrix = doc["nodes"][0]["matrix"]
        if invalid_selector == "nonidentity_matrix":
            matrix[12] = 1
        elif invalid_selector == "boolean_identity_matrix":
            matrix[0] = True
        elif invalid_selector == "short_identity_matrix":
            matrix.pop()
        elif invalid_selector == "mixed_matrix_trs":
            doc["nodes"][0]["translation"] = [0, 0, 0]
        elif invalid_selector == "huge_identity_matrix":
            matrix[0] = 10**400
    if invalid_selector == "node_morph_weights":
        doc["nodes"][0]["weights"] = [0.5]
    elif invalid_selector == "mesh_morph_weights":
        doc["meshes"][0]["weights"] = [0.5]
    if invalid_selector == "animated_node":
        # A valid two-keyframe translation changes the scene at t=1 second.
        # Its bind-pose vertices must not be measured as the animated coral.
        aligned_start = (len(binary) + 3) // 4 * 4
        binary += b"\x00" * (aligned_start - len(binary))
        time_data = struct.pack("<2f", 0.0, 1.0)
        translation_data = struct.pack("<6f", 0, 0, 0, 1, 0, 0)
        doc["bufferViews"].extend(
            [
                {
                    "buffer": 0,
                    "byteOffset": aligned_start,
                    "byteLength": len(time_data),
                },
                {
                    "buffer": 0,
                    "byteOffset": aligned_start + len(time_data),
                    "byteLength": len(translation_data),
                },
            ]
        )
        doc["accessors"].extend(
            [
                {
                    "bufferView": 2,
                    "componentType": 5126,
                    "count": 2,
                    "type": "SCALAR",
                    "min": [0.0],
                    "max": [1.0],
                },
                {"bufferView": 3, "componentType": 5126, "count": 2, "type": "VEC3"},
            ]
        )
        doc["animations"] = [
            {
                "samplers": [{"input": 2, "output": 3, "interpolation": "LINEAR"}],
                "channels": [{"sampler": 0, "target": {"node": 0, "path": "translation"}}],
            }
        ]
        binary += time_data + translation_data
        doc["buffers"][0]["byteLength"] = len(binary)
    elif invalid_selector == "unbound_skin":
        # Even an unbound skin is unsupported metadata in this strict preview.
        doc["skins"] = [{"joints": [0]}]
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
    elif invalid_selector == "index_stride":
        doc["bufferViews"][1]["byteStride"] = 2
    elif invalid_selector == "json_nan":
        doc["extras"] = {"nonfinite": float("nan")}
    elif invalid_selector == "json_infinity":
        doc["extras"] = {"nonfinite": float("inf")}
    elif invalid_selector == "json_negative_infinity":
        doc["extras"] = {"nonfinite": float("-inf")}
    elif invalid_selector in {"json_exponent_overflow", "json_negative_exponent_overflow"}:
        doc["extras"] = {"nonfinite": "overflow_marker"}
    elif invalid_selector in {
        "json_translation_underflow",
        "json_negative_translation_underflow",
        "json_identity_zero_exponent",
    }:
        doc["nodes"][0]["translation"] = ["numeric_marker", 0, 0]
    elif invalid_selector in {
        "json_extras_underflow",
        "json_extras_long_integer",
        "json_extras_oversized_integer",
        "json_extras_bounded_integer",
    }:
        doc["extras"] = {"source_number": "numeric_marker"}
    if explicit_empty_extensions:
        doc["extensionsUsed"] = []
        doc["extensionsRequired"] = []
    if invalid_selector == "extensions_used_object":
        doc["extensionsUsed"] = {}
    elif invalid_selector == "extensions_used_false":
        doc["extensionsUsed"] = False
    elif invalid_selector == "extensions_required_zero":
        doc["extensionsRequired"] = 0
    elif invalid_selector == "extensions_used_nonempty":
        doc["extensionsUsed"] = ["KHR_mesh_quantization"]
    elif invalid_selector == "extensions_root_object":
        doc["extensions"] = {}
    # Nested extension payloads are not safe to ignore, even if the root
    # does not declare extensionsUsed. Extras are opaque user metadata.
    nested_extension_targets = {
        "node_nested_extension": doc["nodes"][0],
        "mesh_nested_extension": doc["meshes"][0],
        "scene_nested_extension": doc["scenes"][0],
        "buffer_nested_extension": doc["buffers"][0],
        "buffer_view_nested_extension": doc["bufferViews"][0],
        "accessor_nested_extension": doc["accessors"][0],
    }
    if invalid_selector in nested_extension_targets:
        nested_extension_targets[invalid_selector]["extensions"] = {"EXT_unhandled": {}}
    elif invalid_selector == "extras_nested_extension_label":
        doc["extras"] = {"extensions": {"arbitrary_note": "not a glTF extension"}}
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
    if explicit_min_version:
        doc["asset"]["minVersion"] = "2.0"
    if explicit_canonical:
        doc["meshes"][0]["primitives"][0]["mode"] = 4
        doc["accessors"][0]["normalized"] = False
        doc["bufferViews"][0]["byteStride"] = 12
    json_bytes = json.dumps(doc).encode()
    if invalid_selector in {"json_exponent_overflow", "json_negative_exponent_overflow"}:
        exponent = b"-1e400" if invalid_selector == "json_negative_exponent_overflow" else b"1e400"
        json_bytes = json_bytes.replace(b'"overflow_marker"', exponent)
    numeric_tokens = {
        "json_translation_underflow": b"1e-9999",
        "json_negative_translation_underflow": b"-1e-9999",
        "json_extras_underflow": b"1e-9999",
        "json_identity_zero_exponent": b"0e-9999",
        "json_extras_long_integer": b"9" * 5000,
        "json_extras_oversized_integer": b"9" * 65,
        "json_extras_bounded_integer": b"9" * 64,
    }
    if invalid_selector in numeric_tokens:
        json_bytes = json_bytes.replace(b'"numeric_marker"', numeric_tokens[invalid_selector])
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


def test_bounded_glb_json_integer_metadata_preserves_geometry() -> None:
    """Opaque bounded JSON integers must not alter decoded scientific geometry."""
    assert parse_glb_triangles(make_glb(invalid_selector="json_extras_bounded_integer")) == (
        parse_glb_triangles(make_glb())
    )


@pytest.mark.parametrize(
    "invalid_selector", ["json_extras_oversized_integer", "json_extras_long_integer"]
)
def test_rejects_oversized_glb_json_integer_tokens(invalid_selector: str) -> None:
    """Reject excessive metadata integers before Python's digit-limit exception."""
    with pytest.raises(ValueError, match="GLB JSON integer exceeds 64-digit preview bound"):
        parse_glb_triangles(make_glb(invalid_selector=invalid_selector))


def test_explicit_glb_minimum_version_preserves_geometry() -> None:
    """A valid glTF 2.0 minimum version does not change decoded geometry."""
    expected = parse_glb_triangles(make_glb())
    actual = parse_glb_triangles(make_glb(explicit_min_version=True))
    assert actual == expected


@pytest.mark.parametrize(
    "invalid_selector",
    ["asset_min_version_future", "asset_min_version_numeric", "asset_min_version_boolean"],
)
def test_rejects_unsupported_glb_minimum_version(invalid_selector: str) -> None:
    """Do not interpret geometry requiring a newer or malformed glTF reader."""
    with pytest.raises(ValueError, match="minimum version"):
        parse_glb_triangles(make_glb(invalid_selector=invalid_selector))


def test_empty_glb_extension_declarations_preserve_geometry() -> None:
    """Valid empty extension arrays do not change the measured geometry."""
    expected = parse_glb_triangles(make_glb())
    actual = parse_glb_triangles(make_glb(explicit_empty_extensions=True))
    assert actual == expected


@pytest.mark.parametrize(
    "invalid_selector",
    [
        "extensions_used_object",
        "extensions_used_false",
        "extensions_required_zero",
        "extensions_used_nonempty",
        "extensions_root_object",
    ],
)
def test_rejects_unsupported_glb_extension_metadata(invalid_selector: str) -> None:
    """Malformed or undeclared extensions cannot be treated as plain geometry."""
    with pytest.raises(ValueError, match=r"extensions|array"):
        parse_glb_triangles(make_glb(invalid_selector=invalid_selector))


@pytest.mark.parametrize(
    "invalid_selector",
    [
        "node_nested_extension",
        "mesh_nested_extension",
        "scene_nested_extension",
        "buffer_nested_extension",
        "buffer_view_nested_extension",
        "accessor_nested_extension",
    ],
)
def test_rejects_undeclared_nested_glb_extensions(invalid_selector: str) -> None:
    """Unsupported per-object extensions cannot silently change measurements."""
    with pytest.raises(ValueError, match="nested extensions"):
        parse_glb_triangles(make_glb(invalid_selector=invalid_selector))


def test_glb_extras_extension_label_is_not_a_gltf_extension() -> None:
    """An arbitrary metadata key inside extras is not a glTF extension."""
    assert parse_glb_triangles(make_glb(invalid_selector="extras_nested_extension_label")) == (
        parse_glb_triangles(make_glb())
    )


def test_single_glb_triangle() -> None:
    vertices, faces = parse_glb_triangles(make_glb())
    assert vertices == [[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 3.0, 0.0]]
    assert faces == [[0, 1, 2]]


@pytest.mark.parametrize("identity_transform", ["translation", "rotation", "scale", "matrix"])
def test_explicit_identity_glb_transform_preserves_geometry(identity_transform: str) -> None:
    """Explicit no-op TRS or matrix must preserve source-frame geometry."""
    assert parse_glb_triangles(make_glb(identity_transform=identity_transform)) == (
        parse_glb_triangles(make_glb())
    )


@pytest.mark.parametrize(
    "invalid_selector",
    [
        "nonidentity_matrix",
        "boolean_identity_matrix",
        "short_identity_matrix",
        "mixed_matrix_trs",
        "huge_identity_matrix",
    ],
)
def test_rejects_nonidentity_or_malformed_glb_matrix(invalid_selector: str) -> None:
    """Unapplied, ambiguous or unbounded matrices cannot define coral dimensions."""
    with pytest.raises(ValueError, match=r"matrix|transforms"):
        parse_glb_triangles(make_glb(invalid_selector=invalid_selector))


def test_rejects_scene_transforms() -> None:
    with pytest.raises(ValueError, match="transforms"):
        parse_glb_triangles(make_glb(translated=True))


@pytest.mark.parametrize(
    "invalid_selector",
    [
        "nonidentity_scale",
        "nonidentity_rotation",
        "boolean_identity_translation",
        "short_identity_translation",
    ],
)
def test_rejects_nonidentity_or_malformed_trs(invalid_selector: str) -> None:
    """Do not silently ignore applied, malformed or Boolean node transforms."""
    with pytest.raises(ValueError, match="transforms"):
        parse_glb_triangles(make_glb(invalid_selector=invalid_selector))


@pytest.mark.parametrize("invalid_selector", ["node_morph_weights", "mesh_morph_weights"])
def test_rejects_unapplied_glb_morph_weights(invalid_selector: str) -> None:
    """Do not measure base vertices while silently ignoring morph weights."""
    with pytest.raises(ValueError, match="morph weights"):
        parse_glb_triangles(make_glb(invalid_selector=invalid_selector))


@pytest.mark.parametrize("invalid_selector", ["animated_node", "unbound_skin"])
def test_rejects_animated_or_skinned_glb(invalid_selector: str) -> None:
    """Do not silently report undeformed vertices as a time-varying scene."""
    with pytest.raises(ValueError, match="animations and skinning"):
        parse_glb_triangles(make_glb(invalid_selector=invalid_selector))


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
    [
        "json_nan",
        "json_infinity",
        "json_negative_infinity",
        "json_exponent_overflow",
        "json_negative_exponent_overflow",
        "json_translation_underflow",
        "json_negative_translation_underflow",
        "json_extras_underflow",
        "nonzero_bin_padding",
    ],
)
def test_rejects_nonstandard_json_and_nonzero_binary_padding(invalid_selector: str) -> None:
    """Nonfinite JSON extensions and nonzero BIN padding are not valid glTF 2.0."""
    with pytest.raises(ValueError, match=r"nonfinite|padding|underflows"):
        parse_glb_triangles(make_glb(invalid_selector=invalid_selector))


def test_genuine_zero_json_exponent_remains_an_identity_transform() -> None:
    """Exact zero must not be confused with an underflowed nonzero transform."""
    expected = parse_glb_triangles(make_glb())
    actual = parse_glb_triangles(make_glb(invalid_selector="json_identity_zero_exponent"))
    assert actual == expected


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
    byte_mesh = parse_glb_triangles(make_glb(unsigned_byte_indices=True))
    short_mesh = parse_glb_triangles(make_glb())
    assert byte_mesh == short_mesh


def test_rejects_out_of_bounds_unsigned_byte_indices() -> None:
    with pytest.raises(ValueError, match="index out of bounds"):
        parse_glb_triangles(make_glb(unsigned_byte_indices=True, invalid_selector="byte_index_oob"))


def test_unsigned_int_indices_match_unsigned_short_geometry() -> None:
    """32-bit glTF triangle indices must preserve geometry and winding."""
    expected = parse_glb_triangles(make_glb())
    actual = parse_glb_triangles(make_glb(unsigned_int_indices=True))
    assert actual == expected


def test_unsigned_int_index_bounds_preserve_geometry() -> None:
    """Optional extrema also bind 32-bit indices to the decoded triangles."""
    expected = parse_glb_triangles(make_glb())
    actual = parse_glb_triangles(make_glb(unsigned_int_indices=True, index_bounds=True))
    assert actual == expected


def test_rejects_out_of_bounds_unsigned_int_indices() -> None:
    """A 32-bit index outside the vertex array cannot become a measurement."""
    with pytest.raises(ValueError, match="index out of bounds"):
        parse_glb_triangles(make_glb(unsigned_int_indices=True, invalid_selector="dword_index_oob"))


def test_glb_position_buffer_view_accepts_four_byte_component_alignment() -> None:
    """glTF float32 VEC3 positions need four-byte, not 12-byte, alignment."""
    offset_mesh = parse_glb_triangles(make_glb(position_offset=4))
    default_mesh = parse_glb_triangles(make_glb())
    assert offset_mesh == default_mesh


@pytest.mark.parametrize("invalid_selector", ["misaligned_position_view", "index_stride"])
def test_rejects_invalid_glb_alignment_or_index_stride(invalid_selector: str) -> None:
    """Reject non-four-byte views and byteStride on index buffer views."""
    with pytest.raises(ValueError, match=r"misaligns|strided"):
        parse_glb_triangles(make_glb(invalid_selector=invalid_selector))


@pytest.mark.parametrize("stride", [12, 16, 20, 252])
def test_interleaved_position_stride_preserves_geometry(stride: int) -> None:
    """POSITION may occupy a subset of each aligned glTF vertex record."""
    assert parse_glb_triangles(make_glb(position_stride=stride)) == parse_glb_triangles(make_glb())


@pytest.mark.parametrize(
    "invalid_selector",
    [
        "stride_too_small",
        "stride_unaligned",
        "stride_oversize",
        "stride_boolean",
        "stride_truncated",
        "stride_overlap",
    ],
)
def test_rejects_invalid_interleaved_glb_stride(invalid_selector: str) -> None:
    """Reject invalid stride metadata and views that truncate the last vertex."""
    with pytest.raises(ValueError, match=r"byteStride|exceeds|misaligns"):
        parse_glb_triangles(make_glb(invalid_selector=invalid_selector))


def test_interleaved_position_with_leading_attribute_bytes() -> None:
    """The POSITION accessor can start four bytes into each vertex record."""
    assert parse_glb_triangles(
        make_glb(position_stride=16, position_leading_bytes=4)
    ) == parse_glb_triangles(make_glb())


def test_valid_glb_position_bounds_match_unannotated_geometry() -> None:
    """Exporter bounds are checked but never treated as scale verification."""
    assert parse_glb_triangles(make_glb(position_bounds=True)) == parse_glb_triangles(make_glb())


@pytest.mark.parametrize(
    "invalid_selector",
    ["bounds_short", "bounds_boolean", "bounds_nan", "bounds_mismatch"],
)
def test_rejects_invalid_or_contradictory_glb_position_bounds(invalid_selector: str) -> None:
    """Untrusted min/max metadata must not contradict the decoded geometry."""
    with pytest.raises(ValueError, match=r"bounds|nonfinite"):
        parse_glb_triangles(make_glb(invalid_selector=invalid_selector))


def test_valid_glb_index_bounds_preserve_geometry() -> None:
    """Optional index extrema are checked, not trusted as independent evidence."""
    assert parse_glb_triangles(make_glb(index_bounds=True)) == parse_glb_triangles(make_glb())


@pytest.mark.parametrize(
    "invalid_selector",
    [
        "index_bounds_short",
        "index_bounds_float",
        "index_bounds_boolean",
        "index_bounds_mismatch",
        "index_bounds_negative",
        "index_bounds_nan",
        "index_bounds_huge",
    ],
)
def test_rejects_invalid_glb_index_bounds(invalid_selector: str) -> None:
    """Malformed or contradictory extrema cannot enter mesh measurements."""
    with pytest.raises(ValueError, match=r"bounds|nonfinite"):
        parse_glb_triangles(make_glb(invalid_selector=invalid_selector))
