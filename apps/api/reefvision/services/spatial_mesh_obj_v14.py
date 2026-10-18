"""Small, local-only OBJ triangle parser for the ReefVision 1.4 preview."""

from __future__ import annotations

from math import isfinite

MAX_OBJ_BYTES = 256_000
MAX_VERTICES = 2_000
MAX_FACES = 4_000


def parse_obj_triangles(text: str) -> tuple[list[list[float]], list[list[int]]]:
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_OBJ_BYTES:
        raise ValueError("OBJ preview exceeds the 256000-byte limit")
    vertices: list[list[float]] = []
    faces: list[list[int]] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        fields = line.strip().split()
        if not fields or fields[0].startswith("#"):
            continue
        if fields[0] == "v":
            if len(fields) < 4:
                raise ValueError(f"OBJ line {line_number}: vertex requires XYZ")
            try:
                point = [float(value) for value in fields[1:4]]
            except ValueError as exc:
                raise ValueError(f"OBJ line {line_number}: invalid vertex") from exc
            if not all(isfinite(value) for value in point):
                raise ValueError(f"OBJ line {line_number}: coordinates must be finite")
            vertices.append(point)
            if len(vertices) > MAX_VERTICES:
                raise ValueError("OBJ preview exceeds vertex limit")
        elif fields[0] == "f":
            if len(fields) != 4:
                raise ValueError(f"OBJ line {line_number}: only triangular faces are supported")
            indices: list[int] = []
            for field in fields[1:]:
                try:
                    index = int(field.split("/")[0])
                except ValueError as exc:
                    raise ValueError(f"OBJ line {line_number}: invalid face index") from exc
                if index == 0:
                    raise ValueError(f"OBJ line {line_number}: OBJ index zero is invalid")
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
