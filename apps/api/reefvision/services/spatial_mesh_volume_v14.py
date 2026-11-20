"""Provisional enclosed volume for a topologically closed triangular mesh patch.

A caller must first verify two-face edge incidence, consistent winding, and
nondegenerate triangles. This does not detect self-intersections, establish
biological completeness, or verify calibration.
"""

from __future__ import annotations

from fractions import Fraction


class EnclosedVolumeUnderflowError(ValueError):
    """A nonzero signed source volume that rounds to zero in binary64."""

    def __init__(self, signed_volume: Fraction) -> None:
        super().__init__("Enclosed mesh volume underflowed numeric precision")
        self.signed_volume = signed_volume


def signed_enclosed_volume_mesh_units(
    points: list[tuple[float, float, float]],
    faces: list[list[int]],
) -> float:
    """Sum oriented tetrahedra exactly on the imported coordinates' binary grid."""
    used_vertices = {index for face in faces for index in face}
    ratios = {
        index: [coordinate.as_integer_ratio() for coordinate in points[index]]
        for index in used_vertices
    }
    # Binary64 denominators are powers of two. The largest is a common
    # denominator, so translating or reversing faces cannot lose a residual.
    denominator = max(divisor for vertex in ratios.values() for _, divisor in vertex)
    origin = [numerator * (denominator // divisor) for numerator, divisor in ratios[faces[0][0]]]
    offsets = {
        index: [
            numerator * (denominator // divisor) - origin[axis]
            for axis, (numerator, divisor) in enumerate(vertex)
        ]
        for index, vertex in ratios.items()
    }
    six_volume = 0
    for a, b, c in faces:
        u, v, w = offsets[a], offsets[b], offsets[c]
        six_volume += (
            u[0] * (v[1] * w[2] - v[2] * w[1])
            + u[1] * (v[2] * w[0] - v[0] * w[2])
            + u[2] * (v[0] * w[1] - v[1] * w[0])
        )
    exact_volume = Fraction(six_volume, 6 * denominator**3)
    try:
        volume = float(exact_volume)
    except OverflowError as exc:
        raise ValueError("Enclosed mesh volume overflowed") from exc
    if volume == 0.0 and exact_volume:
        raise EnclosedVolumeUnderflowError(exact_volume)
    return volume
