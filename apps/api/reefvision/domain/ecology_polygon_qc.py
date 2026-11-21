"""Conservative polygon-topology QC for ecological annotation evidence.

This validates source-pixel rings before they enter longitudinal research
artifacts; it does not certify mask area or biological identity.
"""

from __future__ import annotations

import math

_MAX_SCIENTIFIC_RING_VERTICES = 4096


def _cross(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a: tuple[float, float], b: tuple[float, float], p: tuple[float, float]) -> bool:
    return min(a[0], b[0]) <= p[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])


def _segments_intersect(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> bool:
    ab_c = _cross(a, b, c)
    ab_d = _cross(a, b, d)
    cd_a = _cross(c, d, a)
    cd_b = _cross(c, d, b)
    if ((ab_c > 0 > ab_d) or (ab_c < 0 < ab_d)) and ((cd_a > 0 > cd_b) or (cd_a < 0 < cd_b)):
        return True
    return any(
        (cross == 0 and _on_segment(start, end, point))
        for cross, start, end, point in (
            (ab_c, a, b, c),
            (ab_d, a, b, d),
            (cd_a, c, d, a),
            (cd_b, c, d, b),
        )
    )


def validate_ecological_polygon_topology(points: list[list[int | float]]) -> None:
    """Reject zero-area, self-crossing, or repeated-vertex source polygons.

    An optional repeated first/last vertex is a conventional ring closure.
    Collinear *forward* edges are valid; overlapping/backtracking edges are
    not. The vertex limit bounds worst-case quadratic intersection checks.
    """
    ring = [(float(x), float(y)) for x, y in points]
    if len(ring) > 3 and ring[-1] == ring[0]:
        ring.pop()
    n = len(ring)
    if n < 3 or n > _MAX_SCIENTIFIC_RING_VERTICES:
        raise ValueError("Ecological mask polygon has invalid vertex count")
    if len(set(ring)) != n:
        raise ValueError("Ecological mask polygon repeats a non-closure vertex")
    if not all(math.isfinite(x) and math.isfinite(y) for x, y in ring):
        raise ValueError("Ecological mask polygon has nonfinite coordinates")
    origin = ring[0]
    twice_area = math.fsum(_cross(origin, ring[i], ring[(i + 1) % n]) for i in range(n))
    if not math.isfinite(twice_area) or abs(twice_area) <= 1e-9:
        raise ValueError("Ecological mask polygon has zero or nonfinite projected area")
    for i in range(n):
        previous, vertex, following = ring[i - 1], ring[i], ring[(i + 1) % n]
        if (
            _cross(previous, vertex, following) == 0
            and (
                (vertex[0] - previous[0]) * (following[0] - vertex[0])
                + (vertex[1] - previous[1]) * (following[1] - vertex[1])
            )
            < 0
        ):
            raise ValueError("Ecological mask polygon contains a backtracking edge")
        a, b = vertex, following
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue
            c, d = ring[j], ring[(j + 1) % n]
            if max(a[0], b[0]) < min(c[0], d[0]) or max(c[0], d[0]) < min(a[0], b[0]):
                continue
            if max(a[1], b[1]) < min(c[1], d[1]) or max(c[1], d[1]) < min(a[1], b[1]):
                continue
            if _segments_intersect(a, b, c, d):
                raise ValueError("Ecological mask polygon contains intersecting edges")
