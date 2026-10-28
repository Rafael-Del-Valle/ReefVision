"""Bounded mesh-edge shortest paths, never verified biological branch lengths."""

from __future__ import annotations

from collections import Counter
from heapq import heappop, heappush
from itertools import pairwise
from math import dist, isfinite
from typing import Any


def mesh_edge_paths(
    points: list[tuple[float, float, float]],
    faces: list[list[int]],
    pairs: list[list[int]] | None,
    scale: float,
    scale_uncertainty: float | None,
) -> list[dict[str, Any]] | None:
    if pairs is None:
        return None
    if len(pairs) > 16:
        raise ValueError("A maximum of 16 mesh path pairs is supported")
    referenced = {index for face in faces for index in face}
    adjacency: dict[int, dict[int, float]] = {index: {} for index in referenced}
    edge_incidence: Counter[tuple[int, int]] = Counter()
    edge_orientations: dict[tuple[int, int], list[bool]] = {}
    for a, b, c in faces:
        for first, second in ((a, b), (b, c), (c, a)):
            edge = (min(first, second), max(first, second))
            edge_incidence[edge] += 1
            edge_orientations.setdefault(edge, []).append(first < second)
            length = dist(points[first], points[second])
            if not isfinite(length):
                raise ValueError("Mesh edge length overflowed")
            adjacency[first][second] = length
            adjacency[second][first] = length

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
        parent: dict[int, int] = {}
        queue = [(0.0, start)]
        if not status:
            while queue:
                length, vertex = heappop(queue)
                if length != shortest[vertex]:
                    continue
                if vertex == end:
                    break
                for neighbor, edge_length in sorted(adjacency[vertex].items()):
                    candidate = length + edge_length
                    if candidate < shortest.get(neighbor, float("inf")):
                        shortest[neighbor] = candidate
                        parent[neighbor] = vertex
                        heappush(queue, (candidate, neighbor))
            status = "connected" if end in shortest else "disconnected"
        route: list[int] | None = None
        meters: float | None = None
        chord_m: float | None = None
        detour_ratio: float | None = None
        path_qc_warnings: list[str] | None = None
        path_edge_lengths_m: list[float] | None = None
        path_vertices_in_source_frame_m: list[list[float]] | None = None
        path_edge_length_scale_intervals_m: list[list[float]] | None = None
        if status == "connected":
            route = [end]
            while route[-1] != start:
                route.append(parent[route[-1]])
            route.reverse()
            # Export the complete selected polyline even when render triangles
            # are decimated. Coordinates retain unregistered source axes.
            path_vertices_in_source_frame_m = [
                [coordinate * scale for coordinate in points[index]] for index in route
            ]
            # Preserve every traversed geometric edge for independent route
            # inspection. These are mesh-edge distances, not coral centerlines.
            path_edge_lengths_m = [adjacency[a][b] * scale for a, b in pairwise(route)]
            if any(not isfinite(length) for length in path_edge_lengths_m):
                raise ValueError("Calibrated mesh path segment length overflowed")
            if scale_uncertainty is not None:
                path_edge_length_scale_intervals_m = [
                    [length * (1 - scale_uncertainty), length * (1 + scale_uncertainty)]
                    for length in path_edge_lengths_m
                ]
            meters = shortest[end] * scale
            if not isfinite(meters):
                raise ValueError("Calibrated mesh path length overflowed")
            chord_mesh_units = dist(points[start], points[end])
            chord_m = chord_mesh_units * scale
            if not isfinite(chord_m):
                raise ValueError("Calibrated endpoint chord length overflowed")
            # Compute the dimensionless detour in source units: calibration
            # cancels, and dividing two tiny calibrated lengths loses precision.
            # An underflowed calibrated chord is not a usable physical endpoint
            # distance, however, so do not report a ratio against zero meters.
            detour_ratio = (
                shortest[end] / chord_mesh_units if chord_mesh_units > 0 and chord_m > 0 else None
            )
            # Route flags are topology evidence, not biological branch validation.
            route_edges = [(min(a, b), max(a, b)) for a, b in pairwise(route)]
            path_qc_warnings = []
            if shortest[end] > 0 and meters == 0:
                path_qc_warnings.append("calibrated_path_length_underflow")
            if chord_mesh_units > 0 and chord_m == 0:
                path_qc_warnings.append("calibrated_endpoint_chord_underflow")
            if detour_ratio is not None and not isfinite(detour_ratio):
                detour_ratio = None
                path_qc_warnings.append("geometric_detour_ratio_overflow")
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
            if any(adjacency[a][b] == 0 for a, b in pairwise(route)):
                path_qc_warnings.append("zero_length_edge_on_path")
        results.append(
            {
                "start_vertex_index": start,
                "end_vertex_index": end,
                "status": status,
                "path_vertex_indices": route,
                "path_vertices_in_source_frame_m": path_vertices_in_source_frame_m,
                "path_edge_lengths_m": path_edge_lengths_m,
                "path_edge_length_scale_intervals_m": path_edge_length_scale_intervals_m,
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
                "scale_uncertainty_m": (
                    meters * scale_uncertainty
                    if meters is not None and scale_uncertainty is not None
                    else None
                ),
            }
        )
    return results
