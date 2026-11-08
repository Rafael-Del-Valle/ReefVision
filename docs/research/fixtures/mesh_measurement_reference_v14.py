"""Standalone provisional mesh measurements for Track C research.

Pure-Python, no dependency on the desktop runtime. Input coordinates are in
arbitrary source units; calibration must be supplied explicitly. Triangle area
is surface area of the supplied triangles, not an inferred living coral surface.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

Point = tuple[float, float, float]
Face = tuple[int, int, int]


@dataclass(frozen=True)
class MeshMeasurement:
    triangle_area_units2: float
    surface_area_m2: float
    surface_area_scale_bound_m2: float
    dimensions_m: Point
    dimensions_scale_bound_m: Point
    triangle_count: int
    calibration_review_state: str = "provisional"
    anatomical_review_state: str = "unverified"


def measure_triangle_mesh(
    vertices: Sequence[Point],
    triangles: Sequence[Face],
    *,
    meters_per_unit: float,
    absolute_scale_bound: float,
) -> MeshMeasurement:
    """Measure observed triangles with conservative scale-only bounds.

    Does not estimate occluded surfaces, watertight volume, or anatomical
    uncertainty. Rejects degenerate triangles and invalid calibration.
    """
    if not math.isfinite(meters_per_unit) or meters_per_unit <= 0:
        raise ValueError("meters_per_unit must be positive and finite")
    if not math.isfinite(absolute_scale_bound) or not 0 <= absolute_scale_bound < meters_per_unit:
        raise ValueError("absolute_scale_bound must be finite and less than scale")
    if not vertices or not triangles:
        raise ValueError("nonempty vertices and triangles required")
    if any(len(v) != 3 or any(not math.isfinite(x) for x in v) for v in vertices):
        raise ValueError("vertices must be finite 3D coordinates")
    raw_area = 0.0
    referenced_vertices: set[int] = set()
    seen_faces: set[tuple[int, int, int]] = set()
    for face in triangles:
        if len(face) != 3 or any(type(i) is not int or i < 0 or i >= len(vertices) for i in face):
            raise ValueError("invalid triangle indices")
        a, b, c = (vertices[i] for i in face)
        if len(set(face)) != 3:
            raise ValueError("repeated triangle vertex")
        # Winding is immaterial to surface area; repeated faces inflate it.
        face_key = tuple(sorted(face))
        if face_key in seen_faces:
            raise ValueError("duplicate triangle surface")
        seen_faces.add(face_key)
        referenced_vertices.update(face)
        u = tuple(b[i] - a[i] for i in range(3))
        v = tuple(c[i] - a[i] for i in range(3))
        cross = (u[1] * v[2] - u[2] * v[1],
                 u[2] * v[0] - u[0] * v[2],
                 u[0] * v[1] - u[1] * v[0])
        area = math.hypot(*cross) / 2
        if not math.isfinite(area) or area <= 0:
            raise ValueError("degenerate or overflowing triangle")
        raw_area += area
    if not math.isfinite(raw_area):
        raise ValueError("nonfinite surface area")
    # Unreferenced vertices are not part of the observed triangular surface.
    # Including them would silently inflate reported coral dimensions.
    observed = [vertices[index] for index in sorted(referenced_vertices)]
    spans = tuple(max(v[i] for v in observed) - min(v[i] for v in observed) for i in range(3))
    # Finite source coordinates can still overflow during subtraction or
    # conversion to physical units; never publish infinite measurements.
    if any(not math.isfinite(span) for span in spans):
        raise ValueError("nonfinite observed mesh dimensions")
    scale = meters_per_unit
    delta = absolute_scale_bound
    # Multiply in a stable order: exponentiation can raise OverflowError
    # even when the observed area is tiny enough to yield a finite result.
    nominal_area = (raw_area * scale) * scale
    upper_area = (raw_area * (scale + delta)) * (scale + delta)
    lower_area = (raw_area * (scale - delta)) * (scale - delta)
    # A positive observed surface can underflow to zero after calibration.
    # Zero would misrepresent a nonzero coral surface as absent.
    if nominal_area == 0:
        raise ValueError("calibrated mesh surface area underflow")
    if not math.isfinite(nominal_area) or any(
        not math.isfinite(span * scale) or not math.isfinite(span * delta)
        for span in spans
    ):
        raise ValueError("nonfinite calibrated mesh measurement")
    if not math.isfinite(upper_area) or not math.isfinite(lower_area):
        raise ValueError("nonfinite calibrated mesh uncertainty")
    area_bound = max(upper_area - nominal_area, nominal_area - lower_area)
    if not math.isfinite(area_bound):
        raise ValueError("nonfinite calibrated mesh uncertainty")
    return MeshMeasurement(
        triangle_area_units2=raw_area,
        surface_area_m2=nominal_area,
        surface_area_scale_bound_m2=area_bound,
        dimensions_m=tuple(s * scale for s in spans),
        dimensions_scale_bound_m=tuple(s * delta for s in spans),
        triangle_count=len(triangles),
    )
