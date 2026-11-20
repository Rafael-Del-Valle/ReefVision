"""Triangular mesh measurement helpers."""

from __future__ import annotations

from fractions import Fraction
from math import hypot, isfinite, ulp


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
        cross_products = (
            (u[1] * v[2], u[2] * v[1]),
            (u[2] * v[0], u[0] * v[2]),
            (u[0] * v[1], u[1] * v[0]),
        )
        if any(not isfinite(term) for pair in cross_products for term in pair):
            raise ValueError("3D triangle area overflowed")
        cross = [left - right for left, right in cross_products]
        area = hypot(*cross) / 2

        # Near-parallel source edges can produce a rounded nonzero cross
        # product, or cancel completely, despite a different exact area.
        # Re-evaluate ambiguous determinants over the supplied source floats.
        roundoff_guard = 16 * ulp(1.0)
        cancellation_risk = any(
            max(abs(left), abs(right)) > 0
            and abs(left - right) <= roundoff_guard * max(abs(left), abs(right))
            for left, right in cross_products
        )
        if cancellation_risk or area == 0.0:
            u_exact = [Fraction(b[i]) - Fraction(a[i]) for i in range(3)]
            v_exact = [Fraction(c[i]) - Fraction(a[i]) for i in range(3)]
            cross_exact = (
                u_exact[1] * v_exact[2] - u_exact[2] * v_exact[1],
                u_exact[2] * v_exact[0] - u_exact[0] * v_exact[2],
                u_exact[0] * v_exact[1] - u_exact[1] * v_exact[0],
            )
            if not any(cross_exact):
                return 0.0
            area = hypot(*(float(component) for component in cross_exact)) / 2
    except OverflowError as exc:
        raise ValueError("3D triangle area overflowed") from exc
    if not isfinite(area):
        raise ValueError("3D triangle area overflowed")
    if area == 0.0:
        # Positive area below binary64 precision is not a degenerate surface.
        raise ValueError("3D triangle area underflowed numeric precision")
    return area
