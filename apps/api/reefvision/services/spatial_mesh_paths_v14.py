"""Bounded mesh-edge shortest paths, never verified biological branch lengths."""

from __future__ import annotations

from collections import Counter
from fractions import Fraction
from heapq import heappop, heappush
from itertools import accumulate, pairwise
from math import atan2, degrees, dist, fsum, hypot, isfinite
from typing import Any


def _route_turn_angles(
    points: list[tuple[float, float, float]],
    route: list[int],
    adjacency: dict[int, dict[int, float]],
) -> list[float | None]:
    """Per-vertex geometric turning angles; undefined at ends and zero edges.

    Angles are computed from unit vectors in source coordinates, so a common
    positive calibration scale cancels. They are not anatomical joint angles,
    coral curvature estimates, or uncertainty-qualified measurements.
    """
    angles: list[float | None] = [None] * len(route)
    for offset in range(1, len(route) - 1):
        previous, current, following = route[offset - 1 : offset + 2]
        incoming_length = adjacency[previous][current]
        outgoing_length = adjacency[current][following]
        if incoming_length == 0 or outgoing_length == 0:
            continue
        incoming = [
            (points[current][axis] - points[previous][axis]) / incoming_length for axis in range(3)
        ]
        outgoing = [
            (points[following][axis] - points[current][axis]) / outgoing_length for axis in range(3)
        ]
        cosine = sum(a * b for a, b in zip(incoming, outgoing, strict=True))
        # acos(dot) collapses tiny genuine bends to zero when dot rounds to
        # 1.0. atan2(cross magnitude, dot) retains sub-degree sensitivity
        # while remaining orientation-independent in three dimensions.
        cross = (
            incoming[1] * outgoing[2] - incoming[2] * outgoing[1],
            incoming[2] * outgoing[0] - incoming[0] * outgoing[2],
            incoming[0] * outgoing[1] - incoming[1] * outgoing[0],
        )
        angles[offset] = degrees(atan2(hypot(*cross), cosine))
    return angles


def mesh_edge_paths(
    points: list[tuple[float, float, float]],
    faces: list[list[int]],
    pairs: list[list[int]] | None,
    scale: float,
    scale_uncertainty: float | None,
) -> list[dict[str, Any]] | None:
    if pairs is None:
        return None
    # Direct callers bypass the strict public schema. Python booleans are
    # numeric subclasses, but True must never silently mean one meter/unit
    # or 100% uncertainty. Huge integers must fail as ValueError, not overflow.
    if type(scale) not in (int, float):
        raise ValueError("Mesh path scale must be finite and positive")
    try:
        scale = float(scale)
    except OverflowError as exc:
        raise ValueError("Mesh path scale must be finite and positive") from exc
    if not isfinite(scale) or scale <= 0:
        raise ValueError("Mesh path scale must be finite and positive")
    if scale_uncertainty is not None:
        if type(scale_uncertainty) not in (int, float):
            raise ValueError("Mesh path relative scale uncertainty must be finite and in [0, 1]")
        try:
            scale_uncertainty = float(scale_uncertainty)
        except OverflowError as exc:
            raise ValueError(
                "Mesh path relative scale uncertainty must be finite and in [0, 1]"
            ) from exc
        if not isfinite(scale_uncertainty) or not 0 <= scale_uncertainty <= 1:
            raise ValueError("Mesh path relative scale uncertainty must be finite and in [0, 1]")
    # Validate every source vertex, including unreferenced vertices, before
    # building a graph. Otherwise malformed geometry can escape QC when the
    # selected route never traverses the affected vertex.
    for point in points:
        # Direct callers bypass the strict preview schema. Reject implicit
        # Boolean/string coordinates and huge integers whose conversion to
        # binary64 would overflow, including vertices outside the selected path.
        if (
            not isinstance(point, (list, tuple))
            or len(point) != 3
            or any(type(coordinate) not in (int, float) for coordinate in point)
        ):
            raise ValueError("Mesh path vertices require three finite coordinates")
        try:
            if any(not isfinite(coordinate) for coordinate in point):
                raise ValueError("Mesh path vertices require three finite coordinates")
        except OverflowError as exc:
            raise ValueError("Mesh path vertices require three finite coordinates") from exc
    if len(pairs) > 16:
        raise ValueError("A maximum of 16 mesh path pairs is supported")
    # Direct scientific-engine callers must not bypass mesh topology validation.
    # Negative Python indices otherwise silently refer to unrelated vertices.
    for face in faces:
        if (
            len(face) != 3
            or any(type(index) is not int or index < 0 or index >= len(points) for index in face)
            or len(set(face)) != 3
        ):
            raise ValueError("Mesh path faces require three distinct existing vertex indices")
    referenced = {index for face in faces for index in face}
    adjacency: dict[int, dict[int, float]] = {index: {} for index in referenced}
    edge_incidence: Counter[tuple[int, int]] = Counter()
    edge_orientations: dict[tuple[int, int], list[bool]] = {}
    degenerate_edges: set[tuple[int, int]] = set()
    face_counts = Counter(tuple(sorted(face)) for face in faces)
    duplicate_face_edges: set[tuple[int, int]] = set()
    for a, b, c in faces:
        if face_counts[tuple(sorted((a, b, c)))] > 1:
            duplicate_face_edges.update(
                (min(first, second), max(first, second))
                for first, second in ((a, b), (b, c), (c, a))
            )
        ab = tuple(points[b][axis] - points[a][axis] for axis in range(3))
        ac = tuple(points[c][axis] - points[a][axis] for axis in range(3))
        cross = (
            ab[1] * ac[2] - ab[2] * ac[1],
            ab[2] * ac[0] - ab[0] * ac[2],
            ab[0] * ac[1] - ab[1] * ac[0],
        )
        # Finite vertices and edge distances do not guarantee finite cross
        # products: large coordinate magnitudes can overflow area arithmetic.
        # Reject rather than silently treating an invalid triangle as sound.
        if any(not isfinite(component) for component in cross):
            raise ValueError("Mesh triangle cross product overflowed")
        if all(component == 0 for component in cross):
            degenerate_edges.update(
                (min(first, second), max(first, second))
                for first, second in ((a, b), (b, c), (c, a))
            )
        for first, second in ((a, b), (b, c), (c, a)):
            edge = (min(first, second), max(first, second))
            edge_incidence[edge] += 1
            edge_orientations.setdefault(edge, []).append(first < second)
            length = dist(points[first], points[second])
            if not isfinite(length):
                raise ValueError("Mesh edge length overflowed")
            adjacency[first][second] = length
            adjacency[second][first] = length

    # Positive-weight shortest-path counts are invalidated by zero edges,
    # but only within the connected component containing the requested pair.
    # Unrelated disconnected scans must not make a valid route indeterminate.
    zero_edge_in_component: dict[int, bool] = {}
    component_by_vertex: dict[int, int] = {}
    unseen = set(referenced)
    while unseen:
        seed = min(unseen)
        unseen.remove(seed)
        frontier = [seed]
        component = [seed]
        contains_zero_edge = False
        while frontier:
            vertex = frontier.pop()
            for neighbor, edge_length in adjacency[vertex].items():
                if edge_length == 0.0:
                    contains_zero_edge = True
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    frontier.append(neighbor)
                    component.append(neighbor)
        for vertex in component:
            zero_edge_in_component[vertex] = contains_zero_edge
            component_by_vertex[vertex] = seed

    results: list[dict[str, Any]] = []
    for pair in pairs:
        if (
            len(pair) != 2
            or any(type(index) is not int for index in pair)
            or pair[0] == pair[1]
            or any(index < 0 or index >= len(points) for index in pair)
        ):
            raise ValueError("Surface path requires two distinct existing vertex indices")
        start, end = pair
        status = "unreferenced_endpoint" if start not in referenced or end not in referenced else ""
        shortest = {start: 0.0}
        # Saturate at two: science needs to know whether an equally short
        # alternative exists, not count a potentially exponential path set.
        shortest_counts = {start: 1}
        parent: dict[int, int] = {}
        queue = [(0.0, start)]
        # A strictly positive edge can become numerically free when added to
        # a much larger accumulated cost. Such rounded route ties are not
        # evidence of genuinely equal shortest paths.
        lost_positive_edge_cost = False
        overflowed_candidate_cost = False

        def exact_selected_path_cost(
            vertex: int,
            *,
            path_start: int = start,
            path_parent: dict[int, int] = parent,
        ) -> Fraction:
            """Exact sum of stored binary64 lengths for this pair's parent path.

            Bind the current pair's start and parent map at definition time,
            avoiding late-bound loop variables. Displayed route distances and
            selected Dijkstra paths retain their floating-point semantics.
            """
            total = Fraction(0)
            while vertex != path_start:
                predecessor = path_parent[vertex]
                total += Fraction(adjacency[predecessor][vertex])
                vertex = predecessor
            return total

        if not status:
            while queue:
                length, vertex = heappop(queue)
                if length != shortest[vertex]:
                    continue
                # Continue through all vertices at the destination cost:
                # stopping on the first destination pop can miss another
                # rounded alternative with the same representable cost.
                if end in shortest and length > shortest[end]:
                    break
                for neighbor, edge_length in sorted(adjacency[vertex].items()):
                    candidate = length + edge_length
                    if not isfinite(candidate):
                        # A positive-weight overflow cannot improve any finite
                        # route. Defer the error until all representable routes
                        # are explored: a valid route may be discovered later.
                        overflowed_candidate_cost = True
                        continue
                    if edge_length > 0 and candidate == length:
                        lost_positive_edge_cost = True
                    prior = shortest.get(neighbor, float("inf"))
                    if candidate < prior:
                        shortest[neighbor] = candidate
                        shortest_counts[neighbor] = shortest_counts[vertex]
                        parent[neighbor] = vertex
                        heappush(queue, (candidate, neighbor))
                    elif candidate == prior:
                        # Equal rounded totals need not be equal sums of the
                        # stored source edge lengths. In particular, a tiny
                        # prefix may be lost when a subsequent huge edge is
                        # added, even when no positive edge itself rounds
                        # away against the accumulated prefix.
                        if exact_selected_path_cost(vertex) + Fraction(
                            edge_length
                        ) != exact_selected_path_cost(neighbor):
                            lost_positive_edge_cost = True
                        shortest_counts[neighbor] = min(
                            2, shortest_counts[neighbor] + shortest_counts[vertex]
                        )
            if (
                end not in shortest
                and overflowed_candidate_cost
                and component_by_vertex[start] == component_by_vertex[end]
            ):
                # Topologically connected, but no finite path sum can be
                # represented. Do not misreport numerical failure as a break
                # in the reconstructed surface.
                raise ValueError("Accumulated mesh path length overflowed")
            status = "connected" if end in shortest else "disconnected"
        route: list[int] | None = None
        shortest_route_alternatives_status: str | None = None
        meters: float | None = None
        chord_m: float | None = None
        detour_ratio: float | None = None
        geometric_excess_m: float | None = None
        path_qc_warnings: list[str] | None = None
        path_edge_lengths_m: list[float] | None = None
        path_cumulative_lengths_m: list[float] | None = None
        path_cumulative_length_scale_intervals_m: list[list[float]] | None = None
        path_vertices_in_source_frame_m: list[list[float]] | None = None
        path_edge_length_scale_intervals_m: list[list[float]] | None = None
        path_turn_angles_deg: list[float | None] | None = None
        maximum_turn_angle_deg: float | None = None
        total_absolute_geometric_turn_deg: float | None = None
        if status == "connected":
            if zero_edge_in_component[start]:
                shortest_route_alternatives_status = "unassessable_zero_length_edges"
            elif lost_positive_edge_cost:
                shortest_route_alternatives_status = "unassessable_floating_point_cost_resolution"
            elif shortest_counts[end] > 1:
                shortest_route_alternatives_status = "multiple_exact_equal_cost_routes"
            else:
                shortest_route_alternatives_status = "no_exact_equal_cost_alternative_detected"
            route = [end]
            while route[-1] != start:
                route.append(parent[route[-1]])
            route.reverse()
            # Source-frame turn angles are scale-independent geometric evidence.
            # Endpoints and vertices adjacent to zero-length edges stay unknown.
            path_turn_angles_deg = _route_turn_angles(points, route, adjacency)
            maximum_turn_angle_deg = max(
                (angle for angle in path_turn_angles_deg if angle is not None),
                default=None,
            )
            # Cumulative absolute mesh-polyline turning is scale-independent.
            # An undefined interior turn invalidates the aggregate rather than
            # silently treating missing geometric evidence as a zero bend.
            interior_turns = path_turn_angles_deg[1:-1]
            if all(angle is not None for angle in interior_turns):
                total_absolute_geometric_turn_deg = sum(
                    angle for angle in interior_turns if angle is not None
                )
            # Export the complete selected polyline even when render triangles
            # are decimated. Coordinates retain unregistered source axes.
            path_vertices_in_source_frame_m = [
                [coordinate * scale for coordinate in points[index]] for index in route
            ]
            if any(
                not isfinite(coordinate)
                for vertex in path_vertices_in_source_frame_m
                for coordinate in vertex
            ):
                raise ValueError("Calibrated mesh path vertex coordinate overflowed")
            # Preserve every traversed geometric edge for independent route
            # inspection. These are mesh-edge distances, not coral centerlines.
            path_edge_lengths_m = [adjacency[a][b] * scale for a, b in pairwise(route)]
            if any(not isfinite(length) for length in path_edge_lengths_m):
                raise ValueError("Calibrated mesh path segment length overflowed")
            # One cumulative distance per ordered route vertex allows a reviewer
            # to inspect the full geometric route, including decimated previews.
            # This is not a verified biological centerline or growth estimate.
            path_cumulative_lengths_m = [0.0, *accumulate(path_edge_lengths_m)]
            if any(not isfinite(length) for length in path_cumulative_lengths_m):
                raise ValueError("Calibrated cumulative mesh path length overflowed")
            if scale_uncertainty is not None:
                path_edge_length_scale_intervals_m = [
                    [length * (1 - scale_uncertainty), length * (1 + scale_uncertainty)]
                    for length in path_edge_lengths_m
                ]
                path_cumulative_length_scale_intervals_m = [
                    [length * (1 - scale_uncertainty), length * (1 + scale_uncertainty)]
                    for length in path_cumulative_lengths_m
                ]
            meters = shortest[end] * scale
            if not isfinite(meters):
                raise ValueError("Calibrated mesh path length overflowed")
            chord_mesh_units = dist(points[start], points[end])
            chord_m = chord_mesh_units * scale
            if not isfinite(chord_m):
                raise ValueError("Calibrated endpoint chord length overflowed")
            # The excess over the straight endpoint chord is a geometric
            # detour diagnostic, never an anatomical branch-length estimate.
            # Both distances share the same calibration scale, so uncertainty
            # bounds must scale the difference together (not independently).
            geometric_excess_source_units = max(0.0, shortest[end] - chord_mesh_units)
            geometric_excess_m = geometric_excess_source_units * scale
            if not isfinite(geometric_excess_m):
                raise ValueError("Calibrated geometric detour excess overflowed")
            # Compute the dimensionless detour in source units: calibration
            # cancels, and dividing two tiny calibrated lengths loses precision.
            # An underflowed calibrated chord is not a usable physical endpoint
            # distance, however, so do not report a ratio against zero meters.
            detour_ratio = (
                shortest[end] / chord_mesh_units if chord_mesh_units > 0 and chord_m > 0 else None
            )
            # A finite nominal route can still overflow when its calibration
            # uncertainty is expanded. Never persist nonfinite scientific JSON.
            if scale_uncertainty is not None:
                bounds = [
                    value * factor
                    for value in (
                        meters,
                        chord_m,
                        geometric_excess_m,
                        *path_edge_lengths_m,
                        *path_cumulative_lengths_m,
                    )
                    for factor in (1 - scale_uncertainty, 1 + scale_uncertainty)
                ]
                if any(not isfinite(bound) for bound in bounds):
                    raise ValueError("Calibrated mesh path uncertainty interval overflowed")
            # Route flags are topology evidence, not biological branch validation.
            route_edges = [(min(a, b), max(a, b)) for a, b in pairwise(route)]
            path_qc_warnings = []
            if shortest_route_alternatives_status == "unassessable_zero_length_edges":
                # The selected route can avoid all zero-weight edges even when
                # the same connected mesh component makes route uniqueness
                # unassessable. Surface that limitation in the QC warning list
                # so downstream consumers cannot mistake a clean path for a
                # uniquely determined anatomical branch.
                path_qc_warnings.append("zero_length_mesh_edge_in_connected_component")
            if shortest_route_alternatives_status == "unassessable_floating_point_cost_resolution":
                path_qc_warnings.append("positive_mesh_edge_cost_rounded_away")
            if shortest_route_alternatives_status == "multiple_exact_equal_cost_routes":
                # Turning angles and route shape depend on a deterministic
                # but scientifically arbitrary choice between tied edge paths.
                path_qc_warnings.append("multiple_equal_cost_mesh_routes")
            if shortest[end] > 0 and meters == 0:
                path_qc_warnings.append("calibrated_path_length_underflow")
            if chord_mesh_units == 0 and shortest[end] > 0:
                # Distinct mesh vertices can occupy identical coordinates. A
                # nonzero surface route between them has no usable chord for
                # detour interpretation and needs explicit scientist review.
                path_qc_warnings.append("coincident_route_endpoints")
            if chord_mesh_units > 0 and chord_m == 0:
                path_qc_warnings.append("calibrated_endpoint_chord_underflow")
            if geometric_excess_source_units > 0 and geometric_excess_m == 0:
                path_qc_warnings.append("calibrated_geometric_excess_underflow")
            if detour_ratio is not None and not isfinite(detour_ratio):
                detour_ratio = None
                path_qc_warnings.append("geometric_detour_ratio_overflow")
            if any(edge in degenerate_edges for edge in route_edges):
                path_qc_warnings.append("degenerate_triangle_on_path")
            if any(edge in duplicate_face_edges for edge in route_edges):
                path_qc_warnings.append("duplicate_triangle_on_path")
            if any(edge_incidence[edge] > 2 for edge in route_edges):
                path_qc_warnings.append("nonmanifold_edge_on_path")
            if any(edge_incidence[edge] == 1 for edge in route_edges):
                path_qc_warnings.append("open_boundary_edge_on_path")
            if any(
                len(edge_orientations[edge]) == 2
                and edge_orientations[edge][0] == edge_orientations[edge][1]
                for edge in route_edges
            ):
                path_qc_warnings.append("inconsistent_winding_edge_on_path")
            if any(
                adjacency[a][b] > 0 and calibrated == 0
                for (a, b), calibrated in zip(pairwise(route), path_edge_lengths_m, strict=True)
            ):
                path_qc_warnings.append("calibrated_path_segment_underflow")
            if any(adjacency[a][b] == 0 for a, b in pairwise(route)):
                path_qc_warnings.append("zero_length_edge_on_path")
            if any(
                source != 0 and calibrated == 0
                for index, vertex in zip(route, path_vertices_in_source_frame_m, strict=True)
                for source, calibrated in zip(points[index], vertex, strict=True)
            ):
                path_qc_warnings.append("calibrated_path_vertex_coordinate_underflow")
        results.append(
            {
                "start_vertex_index": start,
                "end_vertex_index": end,
                "status": status,
                "shortest_route_alternatives_status": shortest_route_alternatives_status,
                "path_vertex_indices": route,
                "path_vertices_in_source_frame_m": path_vertices_in_source_frame_m,
                "path_edge_lengths_m": path_edge_lengths_m,
                "path_edge_length_scale_intervals_m": path_edge_length_scale_intervals_m,
                "path_turn_angles_deg": path_turn_angles_deg,
                "maximum_turn_angle_deg": maximum_turn_angle_deg,
                "total_absolute_geometric_turn_deg": total_absolute_geometric_turn_deg,
                "path_cumulative_lengths_m": path_cumulative_lengths_m,
                "path_cumulative_length_scale_intervals_m": (
                    path_cumulative_length_scale_intervals_m
                ),
                "path_qc_warnings": path_qc_warnings,
                "edge_count": len(route) - 1 if route is not None else None,
                "length_m": meters,
                "length_scale_interval_m": (
                    [meters * (1 - scale_uncertainty), meters * (1 + scale_uncertainty)]
                    if meters is not None and scale_uncertainty is not None
                    else None
                ),
                "endpoint_chord_length_m": chord_m,
                "endpoint_chord_scale_interval_m": (
                    [chord_m * (1 - scale_uncertainty), chord_m * (1 + scale_uncertainty)]
                    if chord_m is not None and scale_uncertainty is not None
                    else None
                ),
                "endpoint_chord_scale_uncertainty_m": (
                    chord_m * scale_uncertainty
                    if chord_m is not None and scale_uncertainty is not None
                    else None
                ),
                "geometric_detour_ratio": detour_ratio,
                "geometric_excess_length_m": geometric_excess_m,
                "geometric_excess_scale_interval_m": (
                    [
                        geometric_excess_m * (1 - scale_uncertainty),
                        geometric_excess_m * (1 + scale_uncertainty),
                    ]
                    if geometric_excess_m is not None and scale_uncertainty is not None
                    else None
                ),
                "scale_uncertainty_m": (
                    meters * scale_uncertainty
                    if meters is not None and scale_uncertainty is not None
                    else None
                ),
            }
        )
    return results

def mesh_surface_edge_traces(
    points: list[tuple[float, float, float]],
    faces: list[list[int]],
    vertex_paths: list[list[int]] | None,
    scale: float,
    scale_uncertainty: float | None,
) -> list[dict[str, Any]] | None:
    """Measure caller-traced *existing surface edges*, not coral centerlines.

    An ordered trace deliberately differs from a shortest path: every segment
    must be a real indexed triangle edge. Its length and scale-only interval
    remain explicitly provisional until anatomy and calibration are reviewed.
    """
    if vertex_paths is None:
        return None
    if (
        type(scale) not in (int, float)
        or not isfinite(scale)
        or scale <= 0
        or (
            scale_uncertainty is not None
            and (
                type(scale_uncertainty) not in (int, float)
                or not isfinite(scale_uncertainty)
                or not 0 <= scale_uncertainty <= 1
            )
        )
    ):
        raise ValueError("Surface trace calibration must be finite and within bounds")
    if len(vertex_paths) > 16:
        raise ValueError("At most 16 surface edge traces are supported")

    incidence: Counter[tuple[int, int]] = Counter()
    for face in faces:
        if (
            len(face) != 3
            or any(type(i) is not int or i < 0 or i >= len(points) for i in face)
            or len(set(face)) != 3
        ):
            raise ValueError("Surface trace faces require three distinct existing vertices")
        for a, b in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
            incidence[(min(a, b), max(a, b))] += 1

    traces: list[dict[str, Any]] = []
    for vertices in vertex_paths:
        if (
            not isinstance(vertices, list)
            or not 2 <= len(vertices) <= 128
            or any(type(i) is not int or i < 0 or i >= len(points) for i in vertices)
            or len(set(vertices)) != len(vertices)
        ):
            raise ValueError("Surface traces require 2-128 distinct existing vertex indices")
        edges = [(min(a, b), max(a, b)) for a, b in pairwise(vertices)]
        if any(edge not in incidence for edge in edges):
            raise ValueError("Consecutive surface trace vertices must share a triangle edge")
        try:
            source_lengths = [
                dist(points[a], points[b]) for a, b in pairwise(vertices)
            ]
            segment_lengths = [length * scale for length in source_lengths]
            length_m = fsum(segment_lengths)
            cumulative = [
                0.0,
                *(fsum(segment_lengths[:i]) for i in range(1, len(segment_lengths) + 1)),
            ]
            calibrated_vertices = [
                [coordinate * scale for coordinate in points[index]] for index in vertices
            ]
        except (OverflowError, TypeError, ValueError) as exc:
            raise ValueError("Surface trace geometry cannot be represented") from exc
        if any(
            not isfinite(value)
            for value in (
                *source_lengths,
                *segment_lengths,
                length_m,
                *cumulative,
                *(coordinate for point in calibrated_vertices for coordinate in point),
            )
        ):
            raise ValueError("Surface trace geometry cannot be represented")
        interval = (
            [length_m * (1 - scale_uncertainty), length_m * (1 + scale_uncertainty)]
            if scale_uncertainty is not None
            else None
        )
        if interval is not None and any(not isfinite(bound) for bound in interval):
            raise ValueError("Surface trace scale-only interval overflowed")
        warnings = ["caller_selected_surface_trace_not_anatomical_centerline"]
        if any(incidence[edge] == 1 for edge in edges):
            warnings.append("open_boundary_edge_on_surface_trace")
        if any(incidence[edge] > 2 for edge in edges):
            warnings.append("nonmanifold_edge_on_surface_trace")
        if any(length == 0 for length in source_lengths):
            warnings.append("zero_length_edge_on_surface_trace")
        if any(source > 0 and calibrated == 0 for source, calibrated in zip(
            source_lengths, segment_lengths, strict=True
        )):
            warnings.append("calibrated_surface_trace_segment_underflow")
        if any(source > 0 for source in source_lengths) and length_m == 0:
            warnings.append("calibrated_surface_trace_length_underflow")
        traces.append(
            {
                "trace_type": "caller_selected_mesh_surface_edges",
                "biological_validation_status": "not_verified_anatomical_centerline",
                "human_review_verified": False,
                "vertex_indices": list(vertices),
                "vertices_in_source_frame_m": calibrated_vertices,
                "edge_count": len(edges),
                "segment_lengths_m": segment_lengths,
                "cumulative_lengths_m": cumulative,
                "length_m": length_m,
                "length_scale_only_interval_m": interval,
                "qc_warnings": warnings,
            }
        )
    return traces
