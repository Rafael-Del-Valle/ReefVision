"""Provisional enclosed volume for a topologically closed triangular mesh patch.

A caller must first verify two-face edge incidence, consistent winding, and
nondegenerate triangles. This does not detect self-intersections, establish
biological completeness, or verify calibration.
"""

from __future__ import annotations

from math import fsum, isfinite


def signed_enclosed_volume_mesh_units(
    points: list[tuple[float, float, float]],
    faces: list[list[int]],
) -> float:
    """Compute a translation-stable oriented tetrahedron sum in source units cubed."""
    origin = points[faces[0][0]]
    contributions: list[float] = []
    for a, b, c in faces:
        u = tuple(points[a][axis] - origin[axis] for axis in range(3))
        v = tuple(points[b][axis] - origin[axis] for axis in range(3))
        w = tuple(points[c][axis] - origin[axis] for axis in range(3))
        cross = (
            v[1] * w[2] - v[2] * w[1],
            v[2] * w[0] - v[0] * w[2],
            v[0] * w[1] - v[1] * w[0],
        )
        contribution = fsum(u[axis] * cross[axis] for axis in range(3)) / 6
        if not isfinite(contribution):
            raise ValueError("Enclosed mesh volume overflowed")
        contributions.append(contribution)
    volume = fsum(contributions)
    if not isfinite(volume):
        raise ValueError("Enclosed mesh volume overflowed")
    return volume
