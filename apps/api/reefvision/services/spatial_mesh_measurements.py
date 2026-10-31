"""Triangular mesh measurement helpers."""

from __future__ import annotations

from math import hypot, isfinite


def triangle_area(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
) -> float:
    """Return uncalibrated surface area for one triangle."""
    if not all(isfinite(x) for point in (a, b, c) for x in point):
        raise ValueError("3D coordinates must be finite")
    u = [b[i] - a[i] for i in range(3)]
    v = [c[i] - a[i] for i in range(3)]
    w = [
        u[1] * v[2] - u[2] * v[1],
        u[2] * v[0] - u[0] * v[2],
        u[0] * v[1] - u[1] * v[0],
    ]
    area = hypot(*w) / 2
    if not isfinite(area):
        raise ValueError("3D triangle area overflowed")
    return area
