"""Bounded mesh-edge shortest paths, never verified biological branch lengths."""

from __future__ import annotations

from heapq import heappop, heappush
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
    for a, b, c in faces:
        for first, second in ((a, b), (b, c), (c, a)):
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
        if status == "connected":
            route = [end]
            while route[-1] != start:
                route.append(parent[route[-1]])
            route.reverse()
            meters = shortest[end] * scale
            if not isfinite(meters):
                raise ValueError("Calibrated mesh path length overflowed")
        results.append(
            {
                "start_vertex_index": start,
                "end_vertex_index": end,
                "status": status,
                "path_vertex_indices": route,
                "edge_count": len(route) - 1 if route is not None else None,
                "length_m": meters,
                "scale_uncertainty_m": (
                    meters * scale_uncertainty
                    if meters is not None and scale_uncertainty is not None
                    else None
                ),
            }
        )
    return results
