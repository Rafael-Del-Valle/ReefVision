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
class MeshEdgePathMeasurement:
    """Selected mesh-edge route, not a verified anatomical centerline."""

    vertex_indices: tuple[int, ...]
    length_m: float
    scale_bound_m: float
    anatomical_review_state: str = "unverified"


def measure_selected_mesh_edge_path(
    vertices: Sequence[Point],
    vertex_indices: Sequence[int],
    *,
    meters_per_unit: float,
    absolute_scale_bound: float,
) -> MeshEdgePathMeasurement:
    """Measure an explicitly selected polyline without inferring branch anatomy.

    A selected route must contain at least two distinct consecutive vertices.
    The uncertainty bound represents calibration only, not endpoint placement,
    reconstruction, anatomical identity, or spatial registration.
    """
    if not math.isfinite(meters_per_unit) or meters_per_unit <= 0:
        raise ValueError("meters_per_unit must be positive and finite")
    if not math.isfinite(absolute_scale_bound) or not 0 <= absolute_scale_bound < meters_per_unit:
        raise ValueError("absolute_scale_bound must be finite and less than scale")
    if len(vertex_indices) < 2:
        raise ValueError("selected path requires at least two vertices")
    if any(type(i) is not int or i < 0 or i >= len(vertices) for i in vertex_indices):
        raise ValueError("invalid selected path vertex index")
    selected = [vertices[i] for i in vertex_indices]
    if any(
        len(point) != 3
        or any(type(x) not in (int, float) or not math.isfinite(x) for x in point)
        for point in selected
    ):
        raise ValueError("selected path coordinates must be finite numeric 3D points")
    lengths = [
        math.dist(a, b)
        for a, b in zip(selected, selected[1:])
    ]
    if any(not math.isfinite(length) or length <= 0 for length in lengths):
        raise ValueError("selected path contains zero or nonfinite segment")
    total = math.fsum(lengths)
    if not math.isfinite(total) or any(total == math.fsum(lengths[:i]) for i in range(1, len(lengths))):
        raise ValueError("selected path length lost to numeric precision")
    nominal = total * meters_per_unit
    bound = total * absolute_scale_bound
    if not math.isfinite(nominal) or nominal <= 0 or (absolute_scale_bound > 0 and bound == 0):
        raise ValueError("nonrepresentable calibrated path length")
    if not math.isfinite(bound):
        raise ValueError("nonfinite calibrated path uncertainty")
    return MeshEdgePathMeasurement(tuple(vertex_indices), nominal, bound)


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
    if any(
        len(v) != 3
        or any(
            isinstance(x, bool)
            or not isinstance(x, (int, float))
            or not math.isfinite(x)
            for x in v
        )
        for v in vertices
    ):
        raise ValueError("vertices must be finite numeric 3D coordinates")
    face_areas: list[float] = []
    referenced_vertices: set[int] = set()
    seen_faces: set[tuple[int, int, int]] = set()
    seen_surfaces: set[tuple[Point, Point, Point]] = set()
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
        # Separate vertex indices may still describe the same physical patch.
        # Re-imported seam vertices must not double-count coincident triangles.
        surface_key = tuple(sorted((a, b, c)))
        if surface_key in seen_surfaces:
            raise ValueError("duplicate triangle surface")
        seen_surfaces.add(surface_key)
        referenced_vertices.update(face)
        u = tuple(b[i] - a[i] for i in range(3))
        v = tuple(c[i] - a[i] for i in range(3))
        cross = (u[1] * v[2] - u[2] * v[1],
                 u[2] * v[0] - u[0] * v[2],
                 u[0] * v[1] - u[1] * v[0])
        area = math.hypot(*cross) / 2
        if not math.isfinite(area) or area <= 0:
            raise ValueError("degenerate or overflowing triangle")
        face_areas.append(area)
    # Validate every observed patch against the largest-first accumulation.
    # The former input-order check missed a tiny patch listed before a large
    # triangle: adding the large triangle changed the running sum while
    # silently discarding the earlier patch.
    raw_area = 0.0
    for area in sorted(face_areas, reverse=True):
        next_area = raw_area + area
        if next_area == raw_area:
            raise ValueError("observed triangle area lost to numeric precision")
        raw_area = next_area
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
    # A nonzero observed axis must not silently become zero in physical units.
    # This is distinct from an actually planar mesh with a zero source span.
    if any(span > 0 and span * scale == 0 for span in spans):
        raise ValueError("calibrated mesh dimension underflow")
    # A positive supplied calibration uncertainty must not disappear merely
    # because its physical interval is smaller than float resolution.
    if delta > 0 and any(span > 0 and span * delta == 0 for span in spans):
        raise ValueError("calibrated mesh dimension uncertainty underflow")
    if not math.isfinite(upper_area) or not math.isfinite(lower_area):
        raise ValueError("nonfinite calibrated mesh uncertainty")
    area_bound = max(upper_area - nominal_area, nominal_area - lower_area)
    if not math.isfinite(area_bound):
        raise ValueError("nonfinite calibrated mesh uncertainty")
    # A positive calibration bound must never be represented as a zero
    # surface-area error bar due to endpoint rounding/cancellation.
    if delta > 0 and area_bound == 0:
        raise ValueError("calibrated mesh surface area uncertainty underflow")
    return MeshMeasurement(
        triangle_area_units2=raw_area,
        surface_area_m2=nominal_area,
        surface_area_scale_bound_m2=area_bound,
        dimensions_m=tuple(s * scale for s in spans),
        dimensions_scale_bound_m=tuple(s * delta for s in spans),
        triangle_count=len(triangles),
    )
