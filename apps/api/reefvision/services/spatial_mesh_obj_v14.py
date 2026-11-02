"""Small, local-only OBJ triangle parser for the ReefVision 1.4 preview."""

from __future__ import annotations

from math import isfinite
from re import fullmatch

MAX_OBJ_BYTES = 256_000
MAX_VERTICES = 2_000
MAX_FACES = 4_000
_OBJ_FLOAT_TOKEN = r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"


def _parse_obj_float(token: str) -> float:
    """Read an ASCII OBJ scalar without Python-only syntax or silent underflow."""
    if fullmatch(_OBJ_FLOAT_TOKEN, token) is None:
        raise ValueError("Invalid OBJ floating-point token")
    number = float(token)
    mantissa = token.lower().split("e", 1)[0]
    if number == 0.0 and any(digit in "123456789" for digit in mantissa):
        raise ValueError("Nonzero OBJ scalar underflows floating-point precision")
    if not isfinite(number):
        raise ValueError("OBJ scalar must be finite")
    return number


def parse_obj_triangles(text: str) -> tuple[list[list[float]], list[list[int]]]:
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_OBJ_BYTES:
        raise ValueError("OBJ preview exceeds the 256000-byte limit")
    # splitlines() and split() accept Unicode line/space separators that are
    # not part of the supported ASCII OBJ syntax. Such separators can silently
    # alter record boundaries and therefore change measured mesh geometry.
    # Unicode letters in inert comments/labels remain untouched.
    if any(
        (ord(character) < 32 and character not in "\t\n\r")
        or ord(character) == 127
        or (character.isspace() and character not in " \t\n\r")
        or character == "\ufeff"
        for character in text
    ):
        raise ValueError(
            "OBJ preview contains unsupported control characters or separators"
        )
    vertices: list[list[float]] = []
    faces: list[list[int]] = []
    texture_coordinate_count = 0
    normal_count = 0
    for line_number, line in enumerate(text.splitlines(), 1):
        # OBJ permits trailing # comments on geometry records. Strip only
        # parser tokens; the original bytes remain bound in source provenance.
        fields = line.split("#", 1)[0].strip().split()
        if not fields or fields[0].startswith("#"):
            continue
        if fields[0] == "v":
            # OBJ supports optional homogeneous W and vendor RGB vertex colors.
            # W must be applied before scientific dimensions and area are measured.
            if len(fields) not in {4, 5, 7, 8}:
                raise ValueError(f"OBJ line {line_number}: unsupported vertex layout")
            try:
                point = [_parse_obj_float(value) for value in fields[1:4]]
                if len(fields) in {5, 8}:
                    weight = _parse_obj_float(fields[4])
                    if not isfinite(weight) or weight == 0:
                        raise ValueError("homogeneous weight must be finite and nonzero")
                    normalized = [value / weight for value in point]
                    # Division by a large homogeneous W can collapse a real
                    # source coordinate to zero even when each OBJ scalar
                    # was individually representable. Never measure that
                    # silently altered geometry as if it were exact.
                    if any(
                        value != 0.0 and coordinate == 0.0
                        for value, coordinate in zip(point, normalized, strict=True)
                    ):
                        raise ValueError("homogeneous normalization underflows a coordinate")
                    point = normalized
                if len(fields) in {7, 8}:
                    colors = [_parse_obj_float(value) for value in fields[-3:]]
                    if not all(isfinite(value) for value in colors):
                        raise ValueError("vertex colors must be finite")
            except (ValueError, OverflowError) as exc:
                raise ValueError(f"OBJ line {line_number}: invalid vertex") from exc
            if not all(isfinite(value) for value in point):
                raise ValueError(f"OBJ line {line_number}: coordinates must be finite")
            vertices.append(point)
            if len(vertices) > MAX_VERTICES:
                raise ValueError("OBJ preview exceeds vertex limit")
        elif fields[0] in {"vt", "vn"}:
            # Attribute values do not affect measurements, but malformed or
            # nonfinite declarations must not legitimize face references.
            kind = fields[0]
            count = len(fields) - 1
            if (kind == "vt" and count not in {1, 2, 3}) or (kind == "vn" and count != 3):
                raise ValueError(f"OBJ line {line_number}: invalid {kind} declaration")
            try:
                attributes = [_parse_obj_float(value) for value in fields[1:]]
            except (ValueError, OverflowError) as exc:
                raise ValueError(f"OBJ line {line_number}: invalid {kind} declaration") from exc
            if not all(isfinite(value) for value in attributes):
                raise ValueError(f"OBJ line {line_number}: invalid {kind} declaration")
            if kind == "vt":
                texture_coordinate_count += 1
            else:
                normal_count += 1
        elif fields[0] == "f":
            if len(fields) != 4:
                raise ValueError(f"OBJ line {line_number}: only triangular faces are supported")
            indices: list[int] = []
            for field in fields[1:]:
                # Accept v, v/vt, v//vn, and v/vt/vn. Texture and normal
                # references are not used to compute spatial measurements,
                # but malformed tokens must not silently become valid faces.
                parts = field.split("/")
                if (
                    len(parts) not in {1, 2, 3}
                    or not parts[0]
                    or (len(parts) == 2 and not parts[1])
                    or (len(parts) == 3 and not parts[2])
                ):
                    raise ValueError(f"OBJ line {line_number}: malformed face reference")
                try:
                    if any(part and fullmatch(r"[+-]?[0-9]+", part) is None for part in parts):
                        raise ValueError("non-integer face reference")
                    references = [int(part) for part in parts if part]
                except ValueError as exc:
                    raise ValueError(f"OBJ line {line_number}: invalid face index") from exc
                if 0 in references:
                    raise ValueError(f"OBJ line {line_number}: OBJ index zero is invalid")
                # Attribute records are not used for measurements, but when
                # present their references must resolve to declared records.
                # Legacy files with no vt/vn declarations remain supported.
                for component, available in ((1, texture_coordinate_count), (2, normal_count)):
                    if component < len(parts) and parts[component] and available:
                        attribute_index = int(parts[component])
                        resolved_attribute = (
                            attribute_index - 1
                            if attribute_index > 0
                            else available + attribute_index
                        )
                        if resolved_attribute < 0 or resolved_attribute >= available:
                            raise ValueError(
                                f"OBJ line {line_number}: face attribute index out of bounds"
                            )
                index = references[0]
                resolved = index - 1 if index > 0 else len(vertices) + index
                if resolved < 0 or resolved >= len(vertices):
                    raise ValueError(f"OBJ line {line_number}: face index out of bounds")
                indices.append(resolved)
            faces.append(indices)
            if len(faces) > MAX_FACES:
                raise ValueError("OBJ preview exceeds face limit")
    if not vertices or not faces:
        raise ValueError("OBJ preview requires vertices and triangular faces")
    return vertices, faces
