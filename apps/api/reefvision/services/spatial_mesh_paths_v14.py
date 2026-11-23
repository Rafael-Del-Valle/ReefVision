"""Bounded mesh-edge shortest paths, never verified biological branch lengths."""

from __future__ import annotations

from collections import Counter
from fractions import Fraction
from heapq import heappop, heappush
from itertools import accumulate, pairwise
from math import atan2, degrees, dist, fsum, hypot, isfinite, pi, sqrt
from typing import Any


def _scale_only_length_interval(length_m: float, uncertainty: float | None) -> list[float] | None:
    """Withhold false precision in provisional mesh-edge route scale bounds.

    These bounds are geometric calibration ranges, never biological branch
    lengths or statistical confidence intervals. A genuine zero length, or
    a zero lower bound at 100% relative uncertainty, stays valid.
    """
    if uncertainty is None:
        return None
    lower = length_m * (1 - uncertainty)
    upper = length_m * (1 + uncertainty)
    if length_m > 0 and (
        (uncertainty < 1 and lower == 0.0) or (uncertainty > 0 and lower == upper)
    ):
        return None
    return [lower, upper]


def _complete_scale_only_length_intervals(
    values: list[float], uncertainty: float | None
) -> list[list[float]] | None:
    """Keep ordered trace intervals only when every waypoint bound is representable."""
    if uncertainty is None:
        return None
    bounds = [_scale_only_length_interval(value, uncertainty) for value in values]
    if any(interval is None for interval in bounds):
        return None
    return [interval for interval in bounds if interval is not None]


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
        path_cumulative_lost_positive_segment_indices: list[int] | None = None
        path_calibrated_underflow_segment_indices: list[int] | None = None
        path_calibrated_edge_sum_exact_fraction_m: str | None = None
        path_cumulative_total_exact_match: bool | None = None
        path_cumulative_roundoff_exact_fraction_m: str | None = None
        path_nominal_total_vs_edge_sum_exact_fraction_m: str | None = None
        path_nominal_total_exact_match: bool | None = None
        path_source_edge_sum_minus_chord_exact_fraction: str | None = None
        path_cumulative_length_scale_intervals_m: list[list[float] | None] | None = None
        path_vertices_in_source_frame_m: list[list[float]] | None = None
        path_edge_length_scale_intervals_m: list[list[float] | None] | None = None
        length_scale_interval_m: list[float] | None = None
        endpoint_chord_scale_interval_m: list[float] | None = None
        geometric_excess_scale_interval_m: list[float] | None = None
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
            # Distinguish a strictly positive imported edge that calibrates to
            # binary64 zero from an actual zero-length source edge. These are
            # zero-based route segment positions for full-resolution review.
            path_calibrated_underflow_segment_indices = [
                index
                for index, ((a, b), calibrated) in enumerate(
                    zip(pairwise(route), path_edge_lengths_m, strict=True)
                )
                if adjacency[a][b] > 0 and calibrated == 0
            ]
            # One cumulative distance per ordered route vertex allows a reviewer
            # to inspect the full geometric route, including decimated previews.
            # This is not a verified biological centerline or growth estimate.
            path_cumulative_lengths_m = [0.0, *accumulate(path_edge_lengths_m)]
            if any(not isfinite(length) for length in path_cumulative_lengths_m):
                raise ValueError("Calibrated cumulative mesh path length overflowed")
            # A real positive segment can be too small to advance a large
            # floating-point cumulative distance. Preserve the segment itself
            # and expose precisely which selected route edges lost resolution.
            # These are zero-based segment positions, not biological landmarks.
            path_cumulative_lost_positive_segment_indices = [
                index
                for index, segment_length in enumerate(path_edge_lengths_m)
                if segment_length > 0
                and path_cumulative_lengths_m[index + 1] == path_cumulative_lengths_m[index]
            ]
            # Sum the *stored calibrated binary64 segment lengths* exactly for
            # a reproducible numerical-integrity reference. This does not
            # recover the unknown true geometry or calibration accuracy.
            exact_edge_sum = sum((Fraction(length) for length in path_edge_lengths_m), Fraction(0))
            path_calibrated_edge_sum_exact_fraction_m = str(exact_edge_sum)
            # Signed displayed-minus-exact difference is lossless and auditable.
            # It quantifies binary64 accumulation error, not physical error.
            cumulative_error = Fraction(path_cumulative_lengths_m[-1]) - exact_edge_sum
            path_cumulative_roundoff_exact_fraction_m = str(cumulative_error)
            path_cumulative_total_exact_match = cumulative_error == 0
            meters = shortest[end] * scale
            if not isfinite(meters):
                raise ValueError("Calibrated mesh path length overflowed")
            # The displayed nominal shortest-path length is computed from
            # source-unit Dijkstra totals, whereas the trace accumulates each
            # independently calibrated segment. Neither order of operations
            # is ground truth. Audit their difference against the exact sum
            # of the *stored* calibrated binary64 edge lengths.
            nominal_total_error = Fraction(meters) - exact_edge_sum
            path_nominal_total_vs_edge_sum_exact_fraction_m = str(nominal_total_error)
            path_nominal_total_exact_match = nominal_total_error == 0
            chord_mesh_units = dist(points[start], points[end])
            chord_m = chord_mesh_units * scale
            if not isfinite(chord_m):
                raise ValueError("Calibrated endpoint chord length overflowed")
            # The excess over the straight endpoint chord is a geometric
            # detour diagnostic, never an anatomical branch-length estimate.
            # Both distances share the same calibration scale, so uncertainty
            # bounds must scale the difference together (not independently).
            # An apparently shorter-than-chord route is numeric roundoff,
            # not evidence of exactly zero geometric excess. Withhold the
            # nominal difference and its bounds pending scientist review.
            # A source-unit Dijkstra total may round to the endpoint chord
            # even when the exact sum of its *stored binary64 edge weights*
            # exceeds that rounded chord. Do not claim an exact straight route
            # or zero detour from an unresolved rounded total.
            exact_source_edge_sum = sum(
                (Fraction(adjacency[a][b]) for a, b in pairwise(route)), Fraction(0)
            )
            # Reconcile stored source-edge lengths with the independently
            # rounded endpoint chord using exact rational arithmetic. A
            # negative value signals unresolved binary64 geometry evidence,
            # never negative biological branch or surface distance.
            stored_chord_delta = exact_source_edge_sum - Fraction(chord_mesh_units)
            path_source_edge_sum_minus_chord_exact_fraction = str(stored_chord_delta)
            hidden_excess = shortest[end] == chord_mesh_units and stored_chord_delta > 0
            impossible_stored_chord = stored_chord_delta < 0
            chord_ok = shortest[end] >= chord_mesh_units and not impossible_stored_chord
            usable_excess = chord_ok and not hidden_excess
            geometric_excess_source_units: float | None = None
            if usable_excess:
                geometric_excess_source_units = shortest[end] - chord_mesh_units
            geometric_excess_m = (
                geometric_excess_source_units * scale
                if geometric_excess_source_units is not None
                else None
            )
            if geometric_excess_m is not None and not isfinite(geometric_excess_m):
                raise ValueError("Calibrated geometric detour excess overflowed")
            # Compute the dimensionless detour in source units: calibration
            # cancels, and dividing two tiny calibrated lengths loses precision.
            # An underflowed calibrated chord is not a usable physical endpoint
            # distance, however, so do not report a ratio against zero meters.
            # A geometric mesh route cannot be shorter than its straight
            # endpoint chord. If binary64 operations violate this invariant,
            # withhold the dimensionless detour rather than reporting < 1.
            if chord_mesh_units > 0 and chord_m > 0 and usable_excess:
                detour_ratio = shortest[end] / chord_mesh_units
            # A finite nominal route can still overflow when its calibration
            # uncertainty is expanded. Never persist nonfinite scientific JSON.
            if scale_uncertainty is not None:
                quantities_for_bounds = [
                    meters,
                    chord_m,
                    *path_edge_lengths_m,
                    *path_cumulative_lengths_m,
                ]
                if geometric_excess_m is not None:
                    quantities_for_bounds.append(geometric_excess_m)
                bounds = [
                    value * factor
                    for value in quantities_for_bounds
                    for factor in (1 - scale_uncertainty, 1 + scale_uncertainty)
                ]
                if any(not isfinite(bound) for bound in bounds):
                    raise ValueError("Calibrated mesh path uncertainty interval overflowed")
            # Route flags are topology evidence, not biological branch validation.
            route_edges = [(min(a, b), max(a, b)) for a, b in pairwise(route)]
            path_qc_warnings = []
            if shortest[end] < chord_mesh_units:
                path_qc_warnings.append("endpoint_chord_exceeds_rounded_selected_route")
            if hidden_excess:
                path_qc_warnings.append(
                    "selected_mesh_route_roundoff_hides_stored_edge_chord_excess"
                )
            if impossible_stored_chord:
                path_qc_warnings.append("selected_mesh_route_stored_edge_sum_below_rounded_chord")
            if path_cumulative_lost_positive_segment_indices:
                path_qc_warnings.append(
                    "positive_selected_mesh_segment_lost_in_cumulative_distance"
                )
            if path_cumulative_total_exact_match is False:
                path_qc_warnings.append(
                    "selected_mesh_route_cumulative_roundoff_disagrees_with_exact_edge_sum"
                )
            if path_nominal_total_exact_match is False:
                path_qc_warnings.append(
                    "selected_mesh_route_nominal_total_disagrees_with_exact_edge_sum"
                )
            if scale_uncertainty is not None:
                path_edge_length_scale_intervals_m = [
                    _scale_only_length_interval(length, scale_uncertainty)
                    for length in path_edge_lengths_m
                ]
                path_cumulative_length_scale_intervals_m = [
                    _scale_only_length_interval(length, scale_uncertainty)
                    for length in path_cumulative_lengths_m
                ]
                length_scale_interval_m = _scale_only_length_interval(meters, scale_uncertainty)
                endpoint_chord_scale_interval_m = _scale_only_length_interval(
                    chord_m, scale_uncertainty
                )
                geometric_excess_scale_interval_m = (
                    _scale_only_length_interval(geometric_excess_m, scale_uncertainty)
                    if geometric_excess_m is not None
                    else None
                )
                # A positive distance in the imported source frame can become
                # binary64 zero after applying a tiny physical scale. Such a
                # calibrated zero is not a genuinely zero-length mesh edge,
                # endpoint chord, route, or positive detour. Preserve nominal
                # underflow QC but never publish a false [0, 0] scale bound.
                calibration_underflow = (
                    (shortest[end] > 0 and meters == 0)
                    or (chord_mesh_units > 0 and chord_m == 0)
                    or (
                        geometric_excess_source_units is not None
                        and geometric_excess_source_units > 0
                        and geometric_excess_m == 0
                    )
                    or bool(path_calibrated_underflow_segment_indices)
                )
                if shortest[end] > 0 and meters == 0:
                    length_scale_interval_m = None
                if chord_mesh_units > 0 and chord_m == 0:
                    endpoint_chord_scale_interval_m = None
                if (
                    geometric_excess_source_units is not None
                    and geometric_excess_source_units > 0
                    and geometric_excess_m == 0
                ):
                    geometric_excess_scale_interval_m = None
                positive_source_prefix = False
                for index, (a, b) in enumerate(pairwise(route)):
                    if adjacency[a][b] > 0 and path_edge_lengths_m[index] == 0:
                        path_edge_length_scale_intervals_m[index] = None
                    positive_source_prefix = positive_source_prefix or adjacency[a][b] > 0
                    if positive_source_prefix and path_cumulative_lengths_m[index + 1] == 0:
                        path_cumulative_length_scale_intervals_m[index + 1] = None
                unresolved = (
                    calibration_underflow
                    or (meters > 0 and length_scale_interval_m is None)
                    or (chord_m > 0 and endpoint_chord_scale_interval_m is None)
                    or (
                        geometric_excess_m is not None
                        and geometric_excess_m > 0
                        and geometric_excess_scale_interval_m is None
                    )
                    or any(
                        length > 0 and bounds is None
                        for length, bounds in zip(
                            path_edge_lengths_m, path_edge_length_scale_intervals_m, strict=True
                        )
                    )
                    or any(
                        length > 0 and bounds is None
                        for length, bounds in zip(
                            path_cumulative_lengths_m,
                            path_cumulative_length_scale_intervals_m,
                            strict=True,
                        )
                    )
                )
                if unresolved:
                    path_qc_warnings.append("path_scale_interval_below_numeric_resolution")
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
            if (
                geometric_excess_source_units is not None
                and geometric_excess_source_units > 0
                and geometric_excess_m == 0
            ):
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
            if path_calibrated_underflow_segment_indices:
                path_qc_warnings.append("calibrated_path_segment_underflow")
            if any(adjacency[a][b] == 0 for a, b in pairwise(route)):
                path_qc_warnings.append("zero_length_edge_on_path")
            if any(
                source != 0 and calibrated == 0
                for index, vertex in zip(route, path_vertices_in_source_frame_m, strict=True)
                for source, calibrated in zip(points[index], vertex, strict=True)
            ):
                path_qc_warnings.append("calibrated_path_vertex_coordinate_underflow")
        # Narrow optional nominal lengths before multiplying scale uncertainty.
        # Missing/unrepresentable bounds must never acquire a fabricated
        # absolute uncertainty in API or persisted Workflow Builder results.
        endpoint_chord_scale_uncertainty_m: float | None = None
        route_scale_uncertainty_m: float | None = None
        if scale_uncertainty is not None:
            if chord_m is not None and endpoint_chord_scale_interval_m is not None:
                endpoint_chord_scale_uncertainty_m = chord_m * scale_uncertainty
            if meters is not None and length_scale_interval_m is not None:
                route_scale_uncertainty_m = meters * scale_uncertainty
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
                "path_cumulative_lost_positive_segment_indices": (
                    path_cumulative_lost_positive_segment_indices
                ),
                "path_calibrated_underflow_segment_indices": (
                    path_calibrated_underflow_segment_indices
                ),
                "path_calibrated_edge_sum_exact_fraction_m": (
                    path_calibrated_edge_sum_exact_fraction_m
                ),
                "path_cumulative_total_exact_match": path_cumulative_total_exact_match,
                "path_nominal_total_exact_match": path_nominal_total_exact_match,
                "path_source_edge_sum_minus_chord_exact_fraction": (
                    path_source_edge_sum_minus_chord_exact_fraction
                ),
                "path_nominal_total_vs_edge_sum_exact_fraction_m": (
                    path_nominal_total_vs_edge_sum_exact_fraction_m
                ),
                "path_cumulative_roundoff_exact_fraction_m": (
                    path_cumulative_roundoff_exact_fraction_m
                ),
                "path_cumulative_length_scale_intervals_m": (
                    path_cumulative_length_scale_intervals_m
                ),
                "path_qc_warnings": path_qc_warnings,
                "edge_count": len(route) - 1 if route is not None else None,
                "length_m": meters,
                "length_scale_interval_m": length_scale_interval_m,
                "endpoint_chord_length_m": chord_m,
                "endpoint_chord_scale_interval_m": endpoint_chord_scale_interval_m,
                "endpoint_chord_scale_uncertainty_m": endpoint_chord_scale_uncertainty_m,
                "geometric_detour_ratio": detour_ratio,
                "geometric_excess_length_m": geometric_excess_m,
                "geometric_excess_scale_interval_m": geometric_excess_scale_interval_m,
                "scale_uncertainty_m": route_scale_uncertainty_m,
            }
        )
    return results


_SourcePoint = tuple[float, float, float]
_SourceEdge = tuple[_SourcePoint, _SourcePoint]


def _source_xyz(point: _SourcePoint) -> _SourcePoint:
    """Use a fixed-width hashable XYZ key for tuple and list source vertices."""
    # The direct engine accepts validated three-coordinate lists as well as
    # tuples. tuple(point) loses the fixed-length type needed by mesh QC maps.
    return (point[0], point[1], point[2])


def _closed_loop_exact_source_coplanarity(
    positions: list[_SourcePoint],
) -> tuple[bool | None, list[int]]:
    """Audit exact submitted XYZ, not tolerated physical planarity or anatomical area.

    The final position repeats the first. Fraction preserves the binary64
    source values without scale-dependent rounding or an arbitrary tolerance.
    No plane is defined for collinear or coincident selected waypoints.
    """
    source = [(Fraction(x), Fraction(y), Fraction(z)) for x, y, z in positions[:-1]]
    origin = source[0]
    base: tuple[Fraction, Fraction, Fraction] | None = None
    for point in source[1:]:
        if point != origin:
            base = (
                point[0] - origin[0],
                point[1] - origin[1],
                point[2] - origin[2],
            )
            break
    if base is None:
        return None, []
    normal: tuple[Fraction, Fraction, Fraction] | None = None
    for point in source[1:]:
        other = (
            point[0] - origin[0],
            point[1] - origin[1],
            point[2] - origin[2],
        )
        cross = (
            base[1] * other[2] - base[2] * other[1],
            base[2] * other[0] - base[0] * other[2],
            base[0] * other[1] - base[1] * other[0],
        )
        if any(cross):
            normal = cross
            break
    if normal is None:
        return None, []
    noncoplanar_offsets = [
        index
        for index, point in enumerate(source)
        if (
            normal[0] * (point[0] - origin[0])
            + normal[1] * (point[1] - origin[1])
            + normal[2] * (point[2] - origin[2])
        )
        != 0
    ]
    return not noncoplanar_offsets, noncoplanar_offsets


def _closed_loop_source_segment_intersections(
    positions: list[_SourcePoint],
) -> tuple[list[list[int]], list[list[int]], list[list[int]]]:
    """Audit nonadjacent proper crossings, endpoint contacts, and line overlaps.

    All predicates operate on the submitted binary64 source coordinates
    converted to exact rational values in a nondegenerate source-plane
    projection. This is geometric QC, not physical proximity or contour area.
    The repeated terminal waypoint is excluded from segment enumeration.
    """
    source = [(Fraction(x), Fraction(y), Fraction(z)) for x, y, z in positions[:-1]]
    axes: tuple[int, int] | None = None
    for first, second in ((0, 1), (0, 2), (1, 2)):
        if any(
            (source[i][first] - source[0][first]) * (source[j][second] - source[0][second])
            != (source[i][second] - source[0][second]) * (source[j][first] - source[0][first])
            for i in range(1, len(source))
            for j in range(i + 1, len(source))
        ):
            axes = first, second
            break
    if axes is None:
        return [], [], []
    first, second = axes
    projected = [(point[first], point[second]) for point in source]

    def orient(i: int, j: int, k: int) -> Fraction:
        a, b, c = projected[i], projected[j], projected[k]
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def on_segment(a: int, b: int, c: int) -> bool:
        start, end, point = projected[a], projected[b], projected[c]
        return (
            orient(a, b, c) == 0
            and min(start[0], end[0]) <= point[0] <= max(start[0], end[0])
            and min(start[1], end[1]) <= point[1] <= max(start[1], end[1])
        )

    count = len(projected)
    proper: list[list[int]] = []
    touching: list[list[int]] = []
    overlapping: list[list[int]] = []
    for earlier in range(count):
        for later in range(earlier + 2, count):
            if earlier == 0 and later == count - 1:
                continue  # Consecutive closure edges share their endpoint.
            a, b = earlier, (earlier + 1) % count
            c, d = later, (later + 1) % count
            first_a, first_b = orient(a, b, c), orient(a, b, d)
            second_a, second_b = orient(c, d, a), orient(c, d, b)
            if first_a == first_b == second_a == second_b == 0:
                # Along a common line, strict interval intersection means
                # positive-length overlap; equality is a point contact.
                axis = (
                    0
                    if projected[a][0] != projected[b][0] or projected[c][0] != projected[d][0]
                    else 1
                )
                lower = max(
                    min(projected[a][axis], projected[b][axis]),
                    min(projected[c][axis], projected[d][axis]),
                )
                upper = min(
                    max(projected[a][axis], projected[b][axis]),
                    max(projected[c][axis], projected[d][axis]),
                )
                if lower < upper:
                    overlapping.append([earlier, later])
                elif lower == upper:
                    touching.append([earlier, later])
            elif (
                first_a != 0
                and first_b != 0
                and second_a != 0
                and second_b != 0
                and (first_a > 0) != (first_b > 0)
                and (second_a > 0) != (second_b > 0)
            ):
                proper.append([earlier, later])
            elif (
                on_segment(a, b, c)
                or on_segment(a, b, d)
                or on_segment(c, d, a)
                or on_segment(c, d, b)
            ):
                touching.append([earlier, later])
    return proper, touching, overlapping


def _closed_loop_source_enclosed_planar_area(
    positions: list[_SourcePoint],
) -> float | None:
    """Source-unit area of an already-audited simple planar edge loop.

    A translated exact-rational vector shoelace avoids false cancellation in
    imported source XYZ. Float conversion is only for a representable output;
    unrepresentable positive areas remain unknown, never zero or infinity.
    This footprint is not coral surface area or a verified anatomical section.
    """
    source = [tuple(Fraction(value) for value in point) for point in positions[:-1]]
    origin = source[0]
    twice_area_vector = [Fraction(0), Fraction(0), Fraction(0)]
    for current, following in pairwise([*source, source[0]]):
        a = [value - base for value, base in zip(current, origin, strict=True)]
        b = [value - base for value, base in zip(following, origin, strict=True)]
        twice_area_vector[0] += a[1] * b[2] - a[2] * b[1]
        twice_area_vector[1] += a[2] * b[0] - a[0] * b[2]
        twice_area_vector[2] += a[0] * b[1] - a[1] * b[0]
    if not any(twice_area_vector):
        return None
    try:
        area = hypot(*(float(component / 2) for component in twice_area_vector))
    except OverflowError:
        return None
    return area if isfinite(area) and area > 0 else None


def _closed_loop_source_planar_centroid(
    positions: list[_SourcePoint],
) -> tuple[list[float] | None, bool | None]:
    """Exact polygon centroid and point-in-filled-perimeter QC.

    Both computations use source binary64 values as exact rationals, not
    rounded preview vertices. An area centroid may fall outside a concave
    outline; it is never automatically an organism location or landmark.
    """
    source = [tuple(Fraction(value) for value in point) for point in positions[:-1]]
    origin = source[0]
    translated = [
        tuple(value - base for value, base in zip(point, origin, strict=True)) for point in source
    ]
    following = [*translated[1:], translated[0]]
    for first_axis, second_axis in ((0, 1), (0, 2), (1, 2)):
        weights = [
            point[first_axis] * next_point[second_axis]
            - point[second_axis] * next_point[first_axis]
            for point, next_point in zip(translated, following, strict=True)
        ]
        twice_area = sum(weights, Fraction(0))
        if twice_area == 0:
            continue
        center = [
            origin[axis]
            + sum(
                (
                    (point[axis] + next_point[axis]) * weight
                    for point, next_point, weight in zip(
                        translated, following, weights, strict=True
                    )
                ),
                Fraction(0),
            )
            / (3 * twice_area)
            for axis in range(3)
        ]
        try:
            rounded = [float(value) for value in center]
        except OverflowError:
            return None, None
        if not all(
            isfinite(value) and (value != 0 or exact == 0)
            for value, exact in zip(rounded, center, strict=True)
        ):
            return None, None

        # Deterministic half-open ray crossing on the same nondegenerate
        # projection used for the exact centroid. Boundary points count as
        # inside. No numerical epsilon or arbitrary XY-only projection.
        projected = [(point[first_axis], point[second_axis]) for point in translated]
        query = (
            center[first_axis] - origin[first_axis],
            center[second_axis] - origin[second_axis],
        )
        inside = False
        for start, end in pairwise([*projected, projected[0]]):
            cross = (end[0] - start[0]) * (query[1] - start[1]) - (end[1] - start[1]) * (
                query[0] - start[0]
            )
            if (
                cross == 0
                and min(start[0], end[0]) <= query[0] <= max(start[0], end[0])
                and min(start[1], end[1]) <= query[1] <= max(start[1], end[1])
            ):
                inside = True
                break
            if (start[1] > query[1]) != (end[1] > query[1]):
                crossing_x = start[0] + (
                    (query[1] - start[1]) * (end[0] - start[0]) / (end[1] - start[1])
                )
                if crossing_x > query[0]:
                    inside = not inside
        return rounded, inside
    return None, None


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
    # This engine can be called without FastAPI/Pydantic. Validate the same
    # calibration and every imported source vertex, including unused vertices,
    # so a direct scientific caller cannot bypass the public schema.
    if type(scale) not in (int, float) or (
        scale_uncertainty is not None and type(scale_uncertainty) not in (int, float)
    ):
        raise ValueError("Surface trace calibration must be finite and within bounds")
    try:
        scale = float(scale)
        if scale_uncertainty is not None:
            scale_uncertainty = float(scale_uncertainty)
    except OverflowError as exc:
        raise ValueError("Surface trace calibration must be finite and within bounds") from exc
    if (
        not isfinite(scale)
        or scale <= 0
        or (
            scale_uncertainty is not None
            and (not isfinite(scale_uncertainty) or not 0 <= scale_uncertainty <= 1)
        )
    ):
        raise ValueError("Surface trace calibration must be finite and within bounds")

    for point in points:
        if (
            not isinstance(point, (list, tuple))
            or len(point) != 3
            or any(type(coordinate) not in (int, float) for coordinate in point)
        ):
            raise ValueError("Surface trace vertices require three finite coordinates")
        try:
            if any(not isfinite(coordinate) for coordinate in point):
                raise ValueError("Surface trace vertices require three finite coordinates")
        except OverflowError as exc:
            raise ValueError("Surface trace vertices require three finite coordinates") from exc

    if len(vertex_paths) > 16:
        raise ValueError("At most 16 surface edge traces are supported")

    # Duplicate triangles and inconsistent shared-edge orientation can make
    # a seemingly contiguous scientist-selected trace topologically unreliable.
    # Match the topology audit used by shortest mesh-edge paths.
    incidence: Counter[tuple[int, int]] = Counter()
    # Count original face-edge occurrences by exact source XYZ as well as
    # indexed endpoints. This exposes coincident OBJ/PLY/GLB seams without
    # welding the imported vertices or changing any measured edge.
    geometric_incidence: Counter[_SourceEdge] = Counter()
    geometric_orientations: dict[_SourceEdge, list[bool]] = {}
    edge_orientations: dict[tuple[int, int], list[bool]] = {}
    duplicate_face_edges: set[tuple[int, int]] = set()
    for face in faces:
        if (
            len(face) != 3
            or any(type(i) is not int or i < 0 or i >= len(points) for i in face)
            or len(set(face)) != 3
        ):
            raise ValueError("Surface trace faces require three distinct existing vertices")
    face_counts = Counter(tuple(sorted(face)) for face in faces)
    for face in faces:
        edges_in_face = ((face[0], face[1]), (face[1], face[2]), (face[2], face[0]))
        if face_counts[tuple(sorted(face))] > 1:
            duplicate_face_edges.update((min(a, b), max(a, b)) for a, b in edges_in_face)
        for a, b in edges_in_face:
            edge = (min(a, b), max(a, b))
            incidence[edge] += 1
            source_a, source_b = _source_xyz(points[a]), _source_xyz(points[b])
            geometric_edge = (source_a, source_b) if source_a <= source_b else (source_b, source_a)
            geometric_incidence[geometric_edge] += 1
            geometric_orientations.setdefault(geometric_edge, []).append(source_a < source_b)
            edge_orientations.setdefault(edge, []).append(a < b)

    traces: list[dict[str, Any]] = []
    for vertices in vertex_paths:
        # A closed surface loop explicitly repeats only its initial vertex at
        # the last waypoint. Repeating any intermediate index remains invalid.
        is_closed_surface_loop = (
            isinstance(vertices, list) and len(vertices) >= 4 and vertices[0] == vertices[-1]
        )
        distinct_vertices = vertices[:-1] if is_closed_surface_loop else vertices
        if (
            not isinstance(vertices, list)
            or not 2 <= len(vertices) <= 128
            or any(type(i) is not int or i < 0 or i >= len(points) for i in vertices)
            or len(set(distinct_vertices)) != len(distinct_vertices)
        ):
            raise ValueError(
                "Surface traces require distinct existing indices, except one closing "
                "return after three distinct vertices (2-128 waypoints)"
            )
        edges = [(min(a, b), max(a, b)) for a, b in pairwise(vertices)]
        if any(edge not in incidence for edge in edges):
            raise ValueError("Consecutive surface trace vertices must share a triangle edge")
        try:
            source_lengths = [dist(points[a], points[b]) for a, b in pairwise(vertices)]
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
        # A positive source edge can vanish after calibration. A serialized
        # [0, 0] uncertainty interval would falsely imply a measured zero.
        # Withhold affected collections as a whole to preserve the published
        # array-of-pairs shape for readers of saved scientific artifacts.
        segment_underflow = any(
            source > 0 and calibrated == 0
            for source, calibrated in zip(source_lengths, segment_lengths, strict=True)
        )
        length_underflow = length_m == 0 and any(source > 0 for source in source_lengths)
        interval = (
            _scale_only_length_interval(length_m, scale_uncertainty)
            if not length_underflow
            else None
        )
        if interval is not None and any(not isfinite(bound) for bound in interval):
            raise ValueError("Surface trace scale-only interval overflowed")
        # All waypoints and segments share one calibration factor. These
        # are marginal scale-only bounds, not independent uncertainties to
        # add in quadrature or anatomical/annotation confidence intervals.
        segment_intervals = (
            _complete_scale_only_length_intervals(segment_lengths, scale_uncertainty)
            if not segment_underflow
            else None
        )
        cumulative_intervals = (
            _complete_scale_only_length_intervals(cumulative, scale_uncertainty)
            if not segment_underflow
            else None
        )
        # Use the same source-frame, scale-independent geometric turning
        # calculation as shortest mesh-edge routes. A zero-length neighbor
        # leaves that interior turn unknown; never replace it with zero.
        trace_adjacency: dict[int, dict[int, float]] = {index: {} for index in vertices}
        for (first, second), source_length in zip(pairwise(vertices), source_lengths, strict=True):
            trace_adjacency[first][second] = source_length
            trace_adjacency[second][first] = source_length
        turn_angles_deg = _route_turn_angles(points, vertices, trace_adjacency)
        if is_closed_surface_loop:
            # Measure the return-to-start turn once, at waypoint zero; the
            # duplicated final waypoint has no independent anatomical turn.
            turn_angles_deg[0] = _route_turn_angles(
                points, [vertices[-2], vertices[0], vertices[1]], trace_adjacency
            )[1]
            interior_turn_angles = turn_angles_deg[:-1]
        else:
            interior_turn_angles = turn_angles_deg[1:-1]
        valid_turn_angles = [angle for angle in interior_turn_angles if angle is not None]
        maximum_turn_angle_deg = max(valid_turn_angles, default=None)
        total_absolute_geometric_turn_deg = (
            fsum(valid_turn_angles) if len(valid_turn_angles) == len(interior_turn_angles) else None
        )
        # The endpoint chord is not an anatomical baseline. Source-frame
        # geometry can support a finite scale-invariant detour ratio even if
        # the calibrated meter chord underflows. Withhold only a genuinely
        # coincident source chord or an unrepresentable dimensionless ratio.
        # Measure the chord before applying the shared scale. Computing the
        # distance between separately rounded calibrated display coordinates
        # can erase a genuinely nonzero endpoint separation.
        source_chord = dist(points[vertices[0]], points[vertices[-1]])
        endpoint_chord_m = source_chord * scale
        display_chord_m = dist(calibrated_vertices[0], calibrated_vertices[-1])
        if not isfinite(endpoint_chord_m) or not isfinite(display_chord_m):
            raise ValueError("Surface trace endpoint chord cannot be represented")
        chord_interval = (
            _scale_only_length_interval(endpoint_chord_m, scale_uncertainty)
            if source_chord == 0 or endpoint_chord_m > 0
            else None
        )
        if chord_interval is not None and any(not isfinite(bound) for bound in chord_interval):
            raise ValueError("Surface trace endpoint chord interval overflowed")
        # The same calibration factor multiplies every edge and the chord.
        # Compute this dimensionless diagnostic from source lengths so it
        # cannot change merely because calibrated display positions round.
        try:
            source_trace_length = fsum(source_lengths)
        except OverflowError:
            source_trace_length = float("inf")
        detour_ratio = (
            source_trace_length / source_chord
            if source_chord > 0 and isfinite(source_trace_length)
            else None
        )
        if detour_ratio is not None and not isfinite(detour_ratio):
            detour_ratio = None
        # Preserve unscaled mesh evidence even when a tiny meter-per-unit
        # calibration underflows in binary64. Imported source units are not
        # assumed to be meters or independently validated physical units.
        # An unrepresentably large source total is unknown, never infinity
        # in a persisted scientific JSON artifact.
        source_trace_length_mesh_units = (
            source_trace_length if isfinite(source_trace_length) else None
        )
        # A common calibration scale cancels from waypoint positions along a
        # selected trace. Sum source edge lengths exactly as binary64 rationals
        # before converting dimensionless fractions back to float. This keeps
        # meaningful intermediate positions when calibrated lengths underflow
        # or the unscaled source total exceeds binary64's numeric range.
        # These fractions are not homologous anatomical landmarks.
        exact_source_total = sum((Fraction(length) for length in source_lengths), Fraction(0))
        # Compensated binary64 summation can overflow for an otherwise valid
        # imported surface trace. A scale-independent detour ratio may still
        # be finite because its source-frame endpoint chord is also large.
        # Recover only this ratio from the exact finite edge-length inputs;
        # keep the unrepresentable source total null and preserve all QC.
        if detour_ratio is None and source_chord > 0 and not isfinite(source_trace_length):
            try:
                detour_ratio = float(exact_source_total / Fraction(source_chord))
            except OverflowError:
                detour_ratio = None
        source_cumulative_arc_length_fractions: list[float] | None = None
        if exact_source_total > 0:
            source_cumulative_arc_length_fractions = [0.0]
            exact_source_prefix = Fraction(0)
            for source_length in source_lengths:
                exact_source_prefix += Fraction(source_length)
                source_cumulative_arc_length_fractions.append(
                    float(exact_source_prefix / exact_source_total)
                )
        # Locate positive source edges whose adjacent normalized waypoint
        # positions coincide solely because the displayed fraction rounded.
        # Genuine zero-length edges are reported by separate topology QC.
        source_arc_fraction_resolution_loss_segment_indices = (
            [
                index
                for index, source_length in enumerate(source_lengths)
                if source_length > 0
                and source_cumulative_arc_length_fractions[index]
                == source_cumulative_arc_length_fractions[index + 1]
            ]
            if source_cumulative_arc_length_fractions is not None
            else []
        )
        # Preserve edge-by-edge topology behind aggregate scientific QC.
        # Counts use original indexed faces, not spatially welded vertices;
        # they cannot certify an anatomical coral branch or clean reconstruction.
        face_incidence_counts = [incidence[edge] for edge in edges]
        positions = [_source_xyz(points[index]) for index in vertices]
        # A closed source-edge loop does not necessarily lie in a plane.
        # Exclude its repeated terminal vertex from the exact XYZ audit.
        # A conditional planar footprint below is not mesh surface area.
        source_exact_coplanarity: bool | None = None
        source_noncoplanar_waypoint_offsets: list[int] = []
        proper_crossing_segment_pairs: list[list[int]] | None = None
        touching_segment_pairs: list[list[int]] | None = None
        overlapping_segment_pairs: list[list[int]] | None = None
        if is_closed_surface_loop:
            (
                source_exact_coplanarity,
                source_noncoplanar_waypoint_offsets,
            ) = _closed_loop_exact_source_coplanarity(positions)
            if source_exact_coplanarity is True:
                (
                    proper_crossing_segment_pairs,
                    touching_segment_pairs,
                    overlapping_segment_pairs,
                ) = _closed_loop_source_segment_intersections(positions)
        geometric_face_incidence_counts = [
            geometric_incidence[(start, end) if start <= end else (end, start)]
            for start, end in pairwise(positions)
        ]
        # A selected indexed edge can be on an apparent open boundary even
        # when a separate pair of IDs carries exactly the same source XYZ.
        # Report the mismatch for inspection; do not automatically stitch.
        split_vertex_seam_segment_indices = [
            index
            for index, (indexed, geometric, source_length) in enumerate(
                zip(
                    face_incidence_counts,
                    geometric_face_incidence_counts,
                    source_lengths,
                    strict=True,
                )
            )
            if source_length > 0 and geometric > indexed
        ]
        # Split vertex IDs can conceal a nonmanifold geometric edge: three
        # distinct faces use the same positive-length XYZ segment even though
        # no indexed edge has more than two incident faces. Keep the original
        # topology unchanged; exact coordinate equality is not registration.
        split_vertex_nonmanifold_segment_indices = [
            index
            for index, (indexed, geometric, source_length) in enumerate(
                zip(
                    face_incidence_counts,
                    geometric_face_incidence_counts,
                    source_lengths,
                    strict=True,
                )
            )
            if source_length > 0 and indexed <= 2 and geometric > 2
        ]
        # Geometrically shared edges can also conceal winding errors when
        # their separate vertex IDs make both indexed edges look like borders.
        # Only two-face, positive-length seams have an unambiguous orientation
        # comparison; nonmanifold junctions require independent inspection.
        split_vertex_winding_segment_indices: list[int] = []
        for index, (start, end) in enumerate(pairwise(positions)):
            if (
                source_lengths[index] == 0
                or face_incidence_counts[index] != 1
                or geometric_face_incidence_counts[index] != 2
            ):
                continue
            source_edge = (start, end) if start <= end else (end, start)
            first, second = geometric_orientations[source_edge]
            if first == second:
                split_vertex_winding_segment_indices.append(index)
        open_boundary_segment_indices = [
            index for index, count in enumerate(face_incidence_counts) if count == 1
        ]
        nonmanifold_segment_indices = [
            index for index, count in enumerate(face_incidence_counts) if count > 2
        ]
        duplicate_triangle_segment_indices = [
            index for index, edge in enumerate(edges) if edge in duplicate_face_edges
        ]
        inconsistent_winding_segment_indices = [
            index
            for index, edge in enumerate(edges)
            if len(edge_orientations[edge]) == 2
            and edge_orientations[edge][0] == edge_orientations[edge][1]
        ]
        warnings = ["caller_selected_surface_trace_not_anatomical_centerline"]
        if is_closed_surface_loop:
            warnings.append("closed_surface_trace_not_verified_anatomical_contour")
            if source_exact_coplanarity is False:
                warnings.append("closed_surface_trace_exact_source_noncoplanarity")
            elif source_exact_coplanarity is None:
                warnings.append("closed_surface_trace_source_reference_plane_undefined")
            if proper_crossing_segment_pairs:
                warnings.append("closed_surface_trace_source_proper_self_intersection")
            if touching_segment_pairs:
                warnings.append("closed_surface_trace_source_nonadjacent_segment_contact")
            if overlapping_segment_pairs:
                warnings.append("closed_surface_trace_source_collinear_segment_overlap")
        if source_trace_length_mesh_units is None:
            warnings.append("surface_trace_source_length_unrepresentable")
        if source_cumulative_arc_length_fractions is None:
            warnings.append("surface_trace_source_arc_fractions_undefined_zero_total")
        elif source_arc_fraction_resolution_loss_segment_indices:
            warnings.append("surface_trace_source_arc_fraction_resolution_loss")
        if open_boundary_segment_indices:
            warnings.append("open_boundary_edge_on_surface_trace")
        if split_vertex_seam_segment_indices:
            warnings.append("split_vertex_geometric_seam_on_surface_trace")
        if nonmanifold_segment_indices:
            warnings.append("nonmanifold_edge_on_surface_trace")
        if split_vertex_nonmanifold_segment_indices:
            warnings.append("split_vertex_hidden_nonmanifold_on_surface_trace")
        if split_vertex_winding_segment_indices:
            warnings.append("split_vertex_hidden_winding_conflict_on_surface_trace")
        if duplicate_triangle_segment_indices:
            warnings.append("duplicate_triangle_on_surface_trace")
        if inconsistent_winding_segment_indices:
            warnings.append("inconsistent_winding_edge_on_surface_trace")
        if any(length == 0 for length in source_lengths):
            warnings.append("zero_length_edge_on_surface_trace")
        # A computed 180-degree turn doubles back on the preceding surface
        # segment, even when all selected indices and positions are distinct.
        # This is binary64 geometric QC, not proof of exact anatomical overlap.
        if any(angle == 180.0 for angle in interior_turn_angles if angle is not None):
            warnings.append("surface_trace_180_degree_geometric_turn")
        if source_chord == 0:
            warnings.append("surface_trace_zero_endpoint_chord")
        elif endpoint_chord_m == 0:
            warnings.append("calibrated_surface_trace_endpoint_chord_underflow")
        elif display_chord_m == 0:
            warnings.append("surface_trace_endpoint_chord_display_coordinate_collapse")
        if source_chord > 0 and detour_ratio is None:
            warnings.append("surface_trace_detour_ratio_unrepresentable")
        # Distinct parsed vertex indices can refer to exactly the same XYZ.
        # This makes a selected open-by-index trace return to an earlier
        # location without containing a repeated index or a zero-length edge.
        nonadjacent_coincident_waypoint_index_pairs = [
            [earlier, later]
            for later in range(2, len(positions))
            for earlier in range(later - 1)
            if positions[earlier] == positions[later]
            and not (is_closed_surface_loop and earlier == 0 and later == len(positions) - 1)
        ]
        if nonadjacent_coincident_waypoint_index_pairs:
            warnings.append("nonadjacent_coincident_surface_trace_vertices")
        # Separate imported vertex IDs may describe the same geometric edge.
        # Report every positive-length repeated segment (including a reversed
        # traversal), rather than allowing a seemingly simple indexed path to
        # conceal double-counted length. Exact source XYZ is used; no arbitrary
        # proximity tolerance or unverified anatomical identity is inferred.
        seen_geometric_segments: dict[
            tuple[tuple[float, float, float], tuple[float, float, float]], int
        ] = {}
        repeated_geometric_segment_index_pairs: list[list[int]] = []
        for segment_index, (start, end) in enumerate(pairwise(positions)):
            if source_lengths[segment_index] == 0:
                continue
            geometric_edge = (start, end) if start <= end else (end, start)
            earlier_index = seen_geometric_segments.get(geometric_edge)
            if earlier_index is None:
                seen_geometric_segments[geometric_edge] = segment_index
            else:
                repeated_geometric_segment_index_pairs.append([earlier_index, segment_index])
        # Count only subsequent traversals of an identical source XYZ edge.
        # This is a scale-independent reuse audit, not an inferred correction
        # to the user's trace or a measured coral skeletal branch length.
        reused_source_lengths = [
            source_lengths[later] for _, later in repeated_geometric_segment_index_pairs
        ]
        try:
            reused_source_length = fsum(reused_source_lengths)
        except OverflowError:
            reused_source_length = float("inf")
        reused_source_length_mesh_units = (
            reused_source_length if isfinite(reused_source_length) else None
        )
        # The fraction is dimensionless and can remain well-defined when
        # source-frame mesh-unit sums overflow binary64. Accumulate the
        # already-validated finite source edges as exact binary64 rationals.
        # This is a trace-reuse audit, not corrected anatomical branch length.
        exact_reused_source_length = Fraction(0)
        for reused_length in reused_source_lengths:
            exact_reused_source_length += Fraction(reused_length)
        reused_fraction = (
            float(exact_reused_source_length / exact_source_total)
            if exact_source_total > 0
            else None
        )
        if repeated_geometric_segment_index_pairs:
            warnings.append("surface_trace_reused_geometric_segment")
            if reused_fraction is None:
                warnings.append("surface_trace_reuse_fraction_unrepresentable")
            elif reused_fraction == 0.0:
                # A genuinely reused positive edge may be too small to
                # represent as a nonzero binary64 fraction of the entire trace.
                warnings.append("surface_trace_reuse_fraction_resolution_loss")
        # An exact coplanarity predicate and nonadjacent intersection audit
        # cannot alone certify a simple perimeter: two *adjacent* segments
        # can reverse over the same line. Use rational source coordinates to
        # detect that case without a distance/angle tolerance or mesh welding.
        # This reports provisional geometry only, not a biological contour.
        local_backtrack_waypoint_offsets: list[int] = []
        source_is_simple_planar_perimeter: bool | None = None
        if is_closed_surface_loop and source_exact_coplanarity is True:
            exact_loop = [
                tuple(Fraction(coordinate) for coordinate in point) for point in positions[:-1]
            ]
            for index, current in enumerate(exact_loop):
                previous = exact_loop[index - 1]
                following = exact_loop[(index + 1) % len(exact_loop)]
                incoming = tuple(c - p for c, p in zip(current, previous, strict=True))
                outgoing = tuple(n - c for n, c in zip(following, current, strict=True))
                cross = (
                    incoming[1] * outgoing[2] - incoming[2] * outgoing[1],
                    incoming[2] * outgoing[0] - incoming[0] * outgoing[2],
                    incoming[0] * outgoing[1] - incoming[1] * outgoing[0],
                )
                dot = sum(a * b for a, b in zip(incoming, outgoing, strict=True))
                if not any(cross) and dot < 0:
                    local_backtrack_waypoint_offsets.append(index)
            source_is_simple_planar_perimeter = not (
                proper_crossing_segment_pairs
                or touching_segment_pairs
                or overlapping_segment_pairs
                or nonadjacent_coincident_waypoint_index_pairs
                or repeated_geometric_segment_index_pairs
                or local_backtrack_waypoint_offsets
                or any(length == 0 for length in source_lengths)
            )
            if local_backtrack_waypoint_offsets:
                warnings.append("closed_surface_trace_source_adjacent_backtrack")
        # Only an exactly planar, geometrically simple loop has a meaningful
        # enclosed planar footprint. In particular, do not assign an area to
        # nonplanar loops, bow-ties, contacts, overlaps, or open traces.
        source_planar_area_units2: float | None = None
        calibrated_planar_area_m2: float | None = None
        planar_area_scale_interval_m2: list[float] | None = None
        # A scale-independent shape descriptor for an *unverified* source
        # polygon. Never treat it as organism condition or an anatomical index.
        source_planar_isoperimetric_quotient: float | None = None
        # Circle with the same provisional source-plane footprint. These are
        # geometric descriptors, never verified coral branch or polyp widths.
        source_planar_equivalent_diameter_mesh_units: float | None = None
        calibrated_planar_equivalent_diameter_m: float | None = None
        planar_equivalent_diameter_scale_interval_m: list[float] | None = None
        # Maximum straight-line span between caller-selected vertices of an
        # exactly planar, geometrically simple polygon. This is a provisional
        # polygon dimension, not a coral branch diameter or anatomical width.
        # Evaluate in source coordinates, before calibrated display rounding.
        source_planar_maximum_vertex_chord_mesh_units: float | None = None
        source_planar_maximum_vertex_chord_waypoint_offsets: list[int] | None = None
        # Dimensionless provisional outline elongation: maximum vertex chord
        # divided by the equal-area circle diameter. Both inputs must be
        # representable in original source coordinates; no anatomy is inferred.
        source_planar_chord_to_equivalent_diameter_ratio: float | None = None
        calibrated_planar_maximum_vertex_chord_m: float | None = None
        planar_maximum_vertex_chord_scale_interval_m: list[float] | None = None
        # A provisional filled-outline coordinate centroid, not an anatomical
        # landmark or independently registered colony position.
        source_planar_centroid_mesh_units: list[float] | None = None
        calibrated_planar_centroid_m: list[float] | None = None
        source_planar_centroid_inside_or_on_perimeter: bool | None = None
        if source_is_simple_planar_perimeter is True:
            (
                source_planar_centroid_mesh_units,
                source_planar_centroid_inside_or_on_perimeter,
            ) = _closed_loop_source_planar_centroid(positions)
            if source_planar_centroid_mesh_units is None:
                warnings.append("closed_surface_trace_source_planar_centroid_unrepresentable")
            else:
                if source_planar_centroid_inside_or_on_perimeter is False:
                    warnings.append("closed_surface_trace_source_planar_centroid_outside_perimeter")
                calibrated_center = [
                    coordinate * scale for coordinate in source_planar_centroid_mesh_units
                ]
                if all(isfinite(value) for value in calibrated_center) and all(
                    calibrated != 0 or source == 0
                    for calibrated, source in zip(
                        calibrated_center,
                        source_planar_centroid_mesh_units,
                        strict=True,
                    )
                ):
                    calibrated_planar_centroid_m = calibrated_center
                else:
                    warnings.append(
                        "closed_surface_trace_calibrated_planar_centroid_unrepresentable"
                    )
            # The repeated terminal waypoint is the same source vertex, not
            # an independent candidate. Maximal polygon separation occurs at
            # vertices, even when the polygon is concave. A tied maximum uses
            # the first pair in the submitted order for reproducible provenance.
            unique_waypoint_count = len(positions) - 1
            maximum_source_chord, maximum_pair = max(
                (
                    (dist(positions[earlier], positions[later]), [earlier, later])
                    for earlier in range(unique_waypoint_count)
                    for later in range(earlier + 1, unique_waypoint_count)
                ),
                key=lambda candidate: candidate[0],
            )
            if isfinite(maximum_source_chord) and maximum_source_chord > 0:
                source_planar_maximum_vertex_chord_mesh_units = maximum_source_chord
                source_planar_maximum_vertex_chord_waypoint_offsets = maximum_pair
                calibrated_chord = maximum_source_chord * scale
                if isfinite(calibrated_chord) and calibrated_chord > 0:
                    calibrated_planar_maximum_vertex_chord_m = calibrated_chord
                    if scale_uncertainty is not None:
                        lower = calibrated_chord * (1 - scale_uncertainty)
                        upper = calibrated_chord * (1 + scale_uncertainty)
                        if (
                            isfinite(lower)
                            and isfinite(upper)
                            and (lower > 0 or scale_uncertainty == 1)
                            and upper > 0
                        ):
                            planar_maximum_vertex_chord_scale_interval_m = [lower, upper]
                        else:
                            warnings.append(
                                "closed_surface_trace_planar_maximum_chord_interval_unrepresentable"
                            )
                else:
                    warnings.append(
                        "closed_surface_trace_calibrated_planar_maximum_chord_unrepresentable"
                    )
            else:
                warnings.append("closed_surface_trace_source_planar_maximum_chord_unrepresentable")
            source_planar_area_units2 = _closed_loop_source_enclosed_planar_area(positions)
            if source_planar_area_units2 is None:
                warnings.append("closed_surface_trace_source_planar_area_unrepresentable")
            else:
                # Use sqrt(A)/sqrt(pi) instead of sqrt(A/pi): division by pi
                # can underflow for a positive, representable source area.
                # A linear diameter can remain representable even when its
                # calibrated squared area underflows binary64.
                diameter = 2 * sqrt(source_planar_area_units2) / sqrt(pi)
                if isfinite(diameter) and diameter > 0:
                    source_planar_equivalent_diameter_mesh_units = diameter
                    if source_planar_maximum_vertex_chord_mesh_units is not None:
                        elongation = source_planar_maximum_vertex_chord_mesh_units / diameter
                        if isfinite(elongation) and elongation > 0:
                            source_planar_chord_to_equivalent_diameter_ratio = elongation
                        else:
                            warnings.append(
                                "closed_surface_trace_planar_elongation_ratio_unrepresentable"
                            )
                    calibrated_diameter = diameter * scale
                    if isfinite(calibrated_diameter) and calibrated_diameter > 0:
                        calibrated_planar_equivalent_diameter_m = calibrated_diameter
                        if scale_uncertainty is not None:
                            lower = calibrated_diameter * (1 - scale_uncertainty)
                            upper = calibrated_diameter * (1 + scale_uncertainty)
                            if (
                                isfinite(lower)
                                and isfinite(upper)
                                and (lower > 0 or scale_uncertainty == 1)
                                and upper > 0
                            ):
                                planar_equivalent_diameter_scale_interval_m = [lower, upper]
                            else:
                                warnings.append(
                                    "closed_surface_trace_planar_diameter_interval_unrepresentable"
                                )
                    else:
                        warnings.append(
                            "closed_surface_trace_calibrated_planar_diameter_unrepresentable"
                        )
                else:
                    warnings.append("closed_surface_trace_source_planar_diameter_unrepresentable")
                area_m2 = source_planar_area_units2 * scale * scale
                if isfinite(area_m2) and area_m2 > 0:
                    calibrated_planar_area_m2 = area_m2
                    if scale_uncertainty is not None:
                        lower_scale = scale * (1 - scale_uncertainty)
                        upper_scale = scale * (1 + scale_uncertainty)
                        lower = source_planar_area_units2 * lower_scale * lower_scale
                        upper = source_planar_area_units2 * upper_scale * upper_scale
                        if (
                            isfinite(lower)
                            and isfinite(upper)
                            and (lower > 0 or scale_uncertainty == 1)
                            and upper > 0
                        ):
                            planar_area_scale_interval_m2 = [lower, upper]
                        else:
                            warnings.append(
                                "closed_surface_trace_planar_area_interval_unrepresentable"
                            )
                else:
                    warnings.append("closed_surface_trace_calibrated_planar_area_unrepresentable")
                # The quotient 4*pi*A/P^2 uses source-coordinate area and
                # perimeter, so it is independent of a shared positive scale.
                # sqrt(A)/P avoids overflow in P^2 for large finite geometry.
                # Do not serialize a rounded zero for a positive shape, or
                # fabricate a value if the source perimeter was unrepresentable.
                perimeter = source_trace_length_mesh_units
                if perimeter is not None and perimeter > 0:
                    radius_fraction = sqrt(source_planar_area_units2) / perimeter
                    quotient = 4 * pi * (radius_fraction * radius_fraction)
                    if isfinite(quotient) and 0 < quotient <= 1:
                        source_planar_isoperimetric_quotient = quotient
                if source_planar_isoperimetric_quotient is None:
                    warnings.append("closed_surface_trace_planar_compactness_unrepresentable")
        if scale_uncertainty is not None and (
            (length_m > 0 and interval is None)
            or (endpoint_chord_m > 0 and chord_interval is None)
            or (not segment_underflow and segment_intervals is None)
            or (not segment_underflow and cumulative_intervals is None)
        ):
            warnings.append("surface_trace_scale_interval_below_numeric_resolution")
        if segment_underflow:
            warnings.append("calibrated_surface_trace_segment_underflow")
        # A positive calibrated segment may disappear from cumulative distances
        # when it is smaller than the floating-point resolution of the prefix.
        # Preserve the segment itself and flag that waypoint positions cannot
        # be recovered reliably by differencing the cumulative array.
        if any(
            segment > 0 and cumulative[index] == cumulative[index + 1]
            for index, segment in enumerate(segment_lengths)
        ):
            warnings.append("surface_trace_cumulative_distance_resolution_loss")
        # A positive source edge can disappear from the interactive preview
        # when separately scaled absolute XYZ coordinates round to the same
        # displayed point. This is distinct from segment-length underflow:
        # the independently measured segment may still have positive length.
        collapsed_display_segments = [
            index
            for index, source_length in enumerate(source_lengths)
            if source_length > 0 and calibrated_vertices[index] == calibrated_vertices[index + 1]
        ]
        if collapsed_display_segments:
            warnings.append("surface_trace_segment_display_coordinate_collapse")
        if length_underflow:
            warnings.append("calibrated_surface_trace_length_underflow")
        traces.append(
            {
                "trace_type": "caller_selected_mesh_surface_edges",
                "biological_validation_status": "not_verified_anatomical_centerline",
                "human_review_verified": False,
                "is_closed_surface_loop": is_closed_surface_loop,
                "closed_loop_source_exact_coplanarity": source_exact_coplanarity,
                "closed_loop_source_noncoplanar_waypoint_offsets": (
                    source_noncoplanar_waypoint_offsets
                ),
                "closed_loop_source_proper_crossing_segment_pairs": (proper_crossing_segment_pairs),
                "closed_loop_source_touching_segment_pairs": touching_segment_pairs,
                "closed_loop_source_collinear_overlap_segment_pairs": (overlapping_segment_pairs),
                "closed_loop_source_local_backtrack_waypoint_offsets": (
                    local_backtrack_waypoint_offsets
                ),
                "closed_loop_source_is_simple_planar_perimeter": (
                    source_is_simple_planar_perimeter
                ),
                "closed_loop_source_planar_enclosed_area_mesh_units2": source_planar_area_units2,
                "closed_loop_planar_enclosed_area_m2": calibrated_planar_area_m2,
                "closed_loop_planar_enclosed_area_scale_only_interval_m2": (
                    planar_area_scale_interval_m2
                ),
                "closed_loop_source_planar_isoperimetric_quotient": (
                    source_planar_isoperimetric_quotient
                ),
                "closed_loop_source_planar_centroid_mesh_units": (
                    source_planar_centroid_mesh_units
                ),
                "closed_loop_source_planar_centroid_inside_or_on_perimeter": (
                    source_planar_centroid_inside_or_on_perimeter
                ),
                "closed_loop_planar_centroid_m": calibrated_planar_centroid_m,
                "closed_loop_source_planar_maximum_vertex_chord_mesh_units": (
                    source_planar_maximum_vertex_chord_mesh_units
                ),
                "closed_loop_source_planar_maximum_vertex_chord_waypoint_offsets": (
                    source_planar_maximum_vertex_chord_waypoint_offsets
                ),
                "closed_loop_source_planar_chord_to_equivalent_diameter_ratio": (
                    source_planar_chord_to_equivalent_diameter_ratio
                ),
                "closed_loop_planar_maximum_vertex_chord_m": (
                    calibrated_planar_maximum_vertex_chord_m
                ),
                "closed_loop_planar_maximum_vertex_chord_scale_only_interval_m": (
                    planar_maximum_vertex_chord_scale_interval_m
                ),
                "closed_loop_source_planar_equivalent_diameter_mesh_units": (
                    source_planar_equivalent_diameter_mesh_units
                ),
                "closed_loop_planar_equivalent_diameter_m": (
                    calibrated_planar_equivalent_diameter_m
                ),
                "closed_loop_planar_equivalent_diameter_scale_only_interval_m": (
                    planar_equivalent_diameter_scale_interval_m
                ),
                "vertex_indices": list(vertices),
                "nonadjacent_coincident_waypoint_index_pairs": (
                    nonadjacent_coincident_waypoint_index_pairs
                ),
                "vertices_in_source_frame_m": calibrated_vertices,
                "edge_count": len(edges),
                "segment_lengths_m": segment_lengths,
                "source_segment_lengths_mesh_units": source_lengths,
                "source_trace_length_mesh_units": source_trace_length_mesh_units,
                "source_cumulative_arc_length_fractions": source_cumulative_arc_length_fractions,
                "source_arc_fraction_resolution_loss_segment_indices": (
                    source_arc_fraction_resolution_loss_segment_indices
                ),
                "source_endpoint_chord_mesh_units": source_chord,
                "mesh_edge_face_incidence_counts": face_incidence_counts,
                "geometric_edge_face_incidence_counts": geometric_face_incidence_counts,
                "split_vertex_seam_segment_indices": split_vertex_seam_segment_indices,
                "split_vertex_nonmanifold_segment_indices": (
                    split_vertex_nonmanifold_segment_indices
                ),
                "split_vertex_winding_segment_indices": split_vertex_winding_segment_indices,
                "open_boundary_segment_indices": open_boundary_segment_indices,
                "nonmanifold_segment_indices": nonmanifold_segment_indices,
                "duplicate_triangle_segment_indices": duplicate_triangle_segment_indices,
                "inconsistent_winding_segment_indices": inconsistent_winding_segment_indices,
                "display_coordinate_collapsed_segment_indices": collapsed_display_segments,
                "repeated_geometric_segment_index_pairs": repeated_geometric_segment_index_pairs,
                "reused_geometric_segment_source_length_mesh_units": (
                    reused_source_length_mesh_units
                ),
                "reused_geometric_segment_fraction_of_trace": reused_fraction,
                "turn_angles_deg": turn_angles_deg,
                "maximum_turn_angle_deg": maximum_turn_angle_deg,
                "total_absolute_geometric_turn_deg": total_absolute_geometric_turn_deg,
                "segment_length_scale_only_intervals_m": segment_intervals,
                "cumulative_lengths_m": cumulative,
                "cumulative_length_scale_only_intervals_m": cumulative_intervals,
                "length_m": length_m,
                "length_scale_only_interval_m": interval,
                "endpoint_chord_length_m": endpoint_chord_m,
                "endpoint_chord_scale_only_interval_m": chord_interval,
                "geometric_detour_ratio": detour_ratio,
                "qc_warnings": warnings,
            }
        )
    return traces
