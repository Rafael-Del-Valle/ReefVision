"""Provisional enclosed volume for a topologically closed triangular mesh patch.

A caller must first verify two-face edge incidence, consistent winding, and
nondegenerate triangles. This does not detect self-intersections, establish
biological completeness, or verify calibration.
"""

from __future__ import annotations

from fractions import Fraction
from math import fsum, isfinite, ulp


def signed_enclosed_volume_mesh_units(
    points: list[tuple[float, float, float]],
    faces: list[list[int]],
) -> float:
    """Compute a translation-stable oriented tetrahedron sum in source units cubed."""
    origin = points[faces[0][0]]
    contributions: list[float] = []
    # Even a nonzero floating-point result can be inaccurate if large
    # determinant terms cancel. Recompute from source floats when close to
    # binary64 roundoff instead of trusting the accidental residual.
    cancellation_risk = False
    roundoff_guard = 16 * ulp(1.0)
    for a, b, c in faces:
        u = tuple(points[a][axis] - origin[axis] for axis in range(3))
        v = tuple(points[b][axis] - origin[axis] for axis in range(3))
        w = tuple(points[c][axis] - origin[axis] for axis in range(3))
        cross_products = (
            (v[1] * w[2], v[2] * w[1]),
            (v[2] * w[0], v[0] * w[2]),
            (v[0] * w[1], v[1] * w[0]),
        )
        cross = tuple(left - right for left, right in cross_products)
        if any(
            max(abs(left), abs(right)) > 0
            and abs(left - right) <= roundoff_guard * max(abs(left), abs(right))
            for left, right in cross_products
        ):
            cancellation_risk = True
        dot_terms = [u[axis] * cross[axis] for axis in range(3)]
        six_contribution = fsum(dot_terms)
        if any(dot_terms) and abs(six_contribution) <= roundoff_guard * max(
            abs(term) for term in dot_terms
        ):
            cancellation_risk = True
        contribution = six_contribution / 6
        if not isfinite(contribution):
            raise ValueError("Enclosed mesh volume overflowed")
        contributions.append(contribution)
    volume = fsum(contributions)
    if not isfinite(volume):
        raise ValueError("Enclosed mesh volume overflowed")
    if volume == 0.0 or cancellation_risk:
        # An exact zero or ill-conditioned nonzero determinant may be due to
        # floating-point cancellation. Re-evaluate the ambiguous source-float
        # arithmetic before publishing a signed enclosed volume.
        # This is numeric recovery, not verified calibration or coral volume.
        origin_exact = tuple(Fraction(value) for value in origin)
        exact_six_volume = Fraction(0)
        for a, b, c in faces:
            # Distinct names keep the exact rational path separate from the
            # floating-point vectors above for strict static type checking.
            u_exact = [Fraction(points[a][axis]) - origin_exact[axis] for axis in range(3)]
            v_exact = [Fraction(points[b][axis]) - origin_exact[axis] for axis in range(3)]
            w_exact = [Fraction(points[c][axis]) - origin_exact[axis] for axis in range(3)]
            exact_six_volume = Fraction(
                exact_six_volume
                + u_exact[0] * (v_exact[1] * w_exact[2] - v_exact[2] * w_exact[1])
                + u_exact[1] * (v_exact[2] * w_exact[0] - v_exact[0] * w_exact[2])
                + u_exact[2] * (v_exact[0] * w_exact[1] - v_exact[1] * w_exact[0])
            )
        if not exact_six_volume:
            # Do not publish a spurious nonzero floating-point residual.
            return 0.0
        if exact_six_volume:
            try:
                recovered = float(exact_six_volume / 6)
            except OverflowError as exc:
                raise ValueError("Enclosed mesh volume overflowed") from exc
            if not isfinite(recovered):
                raise ValueError("Enclosed mesh volume overflowed")
            if recovered == 0.0:
                # A real source-coordinate volume below binary64's minimum
                # subnormal cannot be distinguished from an exact zero in
                # scientific output. Reject rather than publishing false zero.
                raise ValueError("Enclosed mesh volume underflowed numeric precision")
            return recovered
    return volume
