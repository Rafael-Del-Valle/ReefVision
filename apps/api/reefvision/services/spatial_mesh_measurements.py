"""Triangular mesh measurement helpers."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
from math import isfinite, sqrt
import json


def triangle_area(a: tuple[float, float, float], b: tuple[float, float, float], c: tuple[float, float, float]) -> float:
    """Return uncalibrated surface area for one triangle."""
    if not all(isfinite(x) for point in (a, b, c) for x in point):
        raise ValueError("3D coordinates must be finite")
    u = [b[i] - a[i] for i in range(3)]
    v = [c[i] - a[i] for i in range(3)]
    w = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
    return sqrt(sum(x * x for x in w)) / 2


def measure_triangular_mesh(vertices: list, faces: list, *, calibration: dict | None = None) -> dict:
    """Calibrated triangle-mesh area and dimensions; never infer enclosed volume."""
    if not isinstance(vertices, list) or not 3 <= len(vertices) <= 100_000:
        raise ValueError("Expected 3–100000 vertices")
    if not isinstance(faces, list) or not 1 <= len(faces) <= 200_000:
        raise ValueError("Expected 1–200000 triangles")
