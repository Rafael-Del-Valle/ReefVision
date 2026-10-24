"""Strict, bounded ASCII PLY triangle preview parser (not a general asset importer)."""

from __future__ import annotations

from math import isfinite

from reefvision.services.spatial_mesh_obj_v14 import MAX_FACES, MAX_VERTICES

MAX_PLY_BYTES = 256_000
_SCALAR_TYPES = {
    "char",
    "uchar",
    "short",
    "ushort",
    "int",
    "uint",
    "float",
    "double",
    "int8",
    "uint8",
    "int16",
    "uint16",
    "int32",
    "uint32",
    "float32",
    "float64",
}

_INTEGER_BOUNDS = {
    "char": (-128, 127),
    "int8": (-128, 127),
    "uchar": (0, 255),
    "uint8": (0, 255),
    "short": (-32768, 32767),
    "int16": (-32768, 32767),
    "ushort": (0, 65535),
    "uint16": (0, 65535),
    "int": (-2147483648, 2147483647),
    "int32": (-2147483648, 2147483647),
    "uint": (0, 4294967295),
    "uint32": (0, 4294967295),
}


def parse_ply_triangles(text: str) -> tuple[list[list[float]], list[list[int]]]:
    """Parse a small ASCII PLY with XYZ vertices and triangular vertex-index faces.

    Reject unsupported elements, binary encodings, polygonal faces, and extra
    body records rather than guessing how to interpret an unknown PLY schema.
    """
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_PLY_BYTES:
        raise ValueError("PLY preview exceeds the 256000-byte limit")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "ply":
        raise ValueError("PLY must begin with the ply magic header")

    element: str | None = None
    counts: dict[str, int] = {}
    vertex_properties: list[str] = []
    vertex_property_types: list[str] = []
    face_property_seen = False
    format_seen = False
    end_header: int | None = None
    for position, raw in enumerate(lines[1:], 1):
        if position > 128:
            raise ValueError("PLY header exceeds 128 lines")
        parts = raw.strip().split()
        if not parts:
            continue
        tag = parts[0]
        if tag == "end_header":
            if len(parts) != 1:
                raise ValueError("Malformed PLY end_header")
            end_header = position
            break
        if tag in {"comment", "obj_info"}:
            continue
        if tag == "format":
            if format_seen or parts != ["format", "ascii", "1.0"]:
                raise ValueError("Only ASCII PLY 1.0 is supported")
            format_seen = True
        elif tag == "element":
            if len(parts) != 3 or parts[1] not in {"vertex", "face"}:
                raise ValueError("PLY preview supports only vertex and face elements")
            name = parts[1]
            if (
                name in counts
                or (name == "face" and "vertex" not in counts)
                or (name == "vertex" and counts)
            ):
                raise ValueError("PLY requires one vertex element before one face element")
            try:
                count = int(parts[2])
            except ValueError as exc:
                raise ValueError("Invalid PLY element count") from exc
            limit = MAX_VERTICES if name == "vertex" else MAX_FACES
            if not 1 <= count <= limit:
                raise ValueError("PLY element count outside preview bounds")
            counts[name] = count
            element = name
        elif tag == "property":
            if element == "vertex":
                if len(parts) != 3 or parts[1] not in _SCALAR_TYPES:
                    raise ValueError("PLY vertex properties must be numeric scalars")
                if parts[2] in vertex_properties:
                    raise ValueError("Duplicate PLY vertex property")
                vertex_properties.append(parts[2])
                vertex_property_types.append(parts[1])
            elif element == "face":
                if (
                    face_property_seen
                    or len(parts) != 5
                    or parts[1] != "list"
                    or parts[2] not in {"uchar", "uint8"}
                    or parts[3] not in {"int", "uint", "int32", "uint32"}
                    or parts[4] not in {"vertex_indices", "vertex_index"}
                ):
                    raise ValueError("PLY faces require one vertex-index list property")
                face_property_seen = True
            else:
                raise ValueError("PLY property declared without an element")
        else:
            raise ValueError(f"Unsupported PLY header directive: {tag}")

    if (
        not format_seen
        or end_header is None
        or set(counts) != {"vertex", "face"}
        or not face_property_seen
        or not {"x", "y", "z"}.issubset(vertex_properties)
    ):
        raise ValueError("Incomplete ASCII PLY triangle header")
    expected = counts["vertex"] + counts["face"]
    rows = lines[end_header + 1 :]
    if len(rows) != expected:
        raise ValueError("PLY body length does not match declared element counts")

    xyz = [vertex_properties.index(axis) for axis in ("x", "y", "z")]
    vertices: list[list[float]] = []
    for row in rows[: counts["vertex"]]:
        values = row.split()
        if len(values) != len(vertex_properties):
            raise ValueError("PLY vertex property count mismatch")
        numeric: list[float] = []
        try:
            for value, scalar_type in zip(values, vertex_property_types, strict=True):
                number: float
                if scalar_type in _INTEGER_BOUNDS:
                    number = int(value)
                    low, high = _INTEGER_BOUNDS[scalar_type]
                    if not low <= number <= high:
                        raise ValueError("PLY integer property outside declared bounds")
                else:
                    number = float(value)
                numeric.append(float(number))
        except (ValueError, OverflowError) as exc:
            raise ValueError("Invalid or out-of-range PLY vertex value") from exc
        if not all(isfinite(value) for value in numeric):
            raise ValueError("PLY vertex properties must be finite")
        vertices.append([numeric[index] for index in xyz])

    faces: list[list[int]] = []
    for row in rows[counts["vertex"] :]:
        values = row.split()
        if len(values) != 4 or values[0] != "3":
            raise ValueError("PLY preview supports only triangular faces")
        try:
            indices = [int(value) for value in values[1:]]
        except ValueError as exc:
            raise ValueError("Invalid PLY face index") from exc
        if any(index < 0 or index >= len(vertices) for index in indices):
            raise ValueError("PLY face index out of bounds")
        faces.append(indices)
    return vertices, faces
