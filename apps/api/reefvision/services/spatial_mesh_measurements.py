"""Triangular mesh measurement helpers."""

from __future__ import annotations

from math import isfinite, sqrt


def triangle_area(a: tuple[float, float, float], b: tuple[float, float, float], c: tuple[float, float, float]) -> float:
    """Return uncalibrated surface area for one triangle."""
    if not all(isfinite(x) for point in (a, b, c) for x in point):
        raise ValueError("3D coordinates must be finite")
    u = [b[i] - a[i] for i in range(3)]
    v = [c[i] - a[i] for i in range(3)]
    w = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
    return sqrt(sum(x * x for x in w)) / 2
