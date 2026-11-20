"""Triangular mesh measurement helpers."""

from __future__ import annotations

from fractions import Fraction
from math import hypot, isfinite


def triangle_area(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
) -> float:
    """Return uncalibrated surface area for one triangle."""
    if any(not isinstance(point, (tuple, list)) or len(point) != 3 for point in (a, b, c)):
        raise ValueError("3D coordinates must contain exactly three components")
    for point in (a, b, c):
        for coordinate in point:
            if type(coordinate) not in (int, float):
                raise ValueError("3D coordinates must be finite real numbers")
            try:
                finite = isfinite(coordinate)
            except OverflowError as exc:
                raise ValueError("3D coordinates must be finite real numbers") from exc
            if not finite:
                raise ValueError("3D coordinates must be finite real numbers")
    try:
        u = [b[i] - a[i] for i in range(3)]
        v = [c[i] - a[i] for i in range(3)]
        w = [
            u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0],
        ]
        area = hypot(*w) / 2
    except OverflowError as exc:
        raise ValueError("3D triangle area overflowed") from exc
    if not isfinite(area):
        raise ValueError("3D triangle area overflowed")
    if area == 0.0:
        # A tiny but genuinely non-collinear source triangle can lose its
        # cross product (or half its norm) to binary64 underflow. Returning
        # zero would misclassify reconstructed surface as degenerate tissue.
        # Exact rational predicates are needed only on the zero-area path.
        u_exact = [Fraction(b[i]) - Fraction(a[i]) for i in range(3)]
        v_exact = [Fraction(c[i]) - Fraction(a[i]) for i in range(3)]
        cross_exact = (
            u_exact[1] * v_exact[2] - u_exact[2] * v_exact[1],
            u_exact[2] * v_exact[0] - u_exact[0] * v_exact[2],
            u_exact[0] * v_exact[1] - u_exact[1] * v_exact[0],
        )
        if any(cross_exact):
            raise ValueError("3D triangle area underflowed numeric precision")
    return area
