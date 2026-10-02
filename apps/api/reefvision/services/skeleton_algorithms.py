"""Topology-preserving binary skeleton algorithms for coral structure analysis."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from math import hypot
from typing import Literal

BinaryMask = tuple[bytes, int, int]
SkeletonPixelKind = Literal["isolated", "endpoint", "path", "junction"]

_NEIGHBORS_8 = (
    (-1, -1),
    (0, -1),
    (1, -1),
    (-1, 0),
    (1, 0),
    (-1, 1),
    (0, 1),
    (1, 1),
)


@dataclass(frozen=True, slots=True)
class SkeletonPixelFeature:
    x: int
    y: int
    degree: int
    kind: SkeletonPixelKind


@dataclass(frozen=True, slots=True)
class SkeletonJunctionCluster:
    id: str
    pixels: tuple[tuple[int, int], ...]
    centroid_x: float
    centroid_y: float
    representative_x: int
    representative_y: int
    external_connections: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class SkeletonGraphNode:
    id: str
    kind: Literal["endpoint", "junction", "isolated", "cycle_anchor"]
    x: float
    y: float
    source_pixels: tuple[tuple[int, int], ...]
    external_connection_count: int


@dataclass(frozen=True, slots=True)
class SkeletonGraphEdge:
    id: str
    source_node_id: str
    target_node_id: str
    pixels: tuple[tuple[int, int], ...]
    boundary_to_boundary_length_pixels: float
    is_cycle: bool


@dataclass(frozen=True, slots=True)
class SkeletonSpurRemoval:
    iteration: int
    branch_id: str
    endpoint_x: int
    endpoint_y: int
    junction_id: str
    branch_length_pixels: float
    removed_pixels: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class SkeletonPruningResult:
    mask: BinaryMask
    removals: tuple[SkeletonSpurRemoval, ...]
    graph_nodes: tuple[SkeletonGraphNode, ...]
    graph_edges: tuple[SkeletonGraphEdge, ...]


def _value(pixels: bytearray, width: int, height: int, x: int, y: int) -> int:
    if x < 0 or y < 0 or x >= width or y >= height:
        return 0
    return pixels[y * width + x]


def _ordered_neighbors(
    pixels: bytearray,
    width: int,
    height: int,
    x: int,
    y: int,
) -> tuple[int, int, int, int, int, int, int, int]:
    return (
        _value(pixels, width, height, x, y - 1),
        _value(pixels, width, height, x + 1, y - 1),
        _value(pixels, width, height, x + 1, y),
        _value(pixels, width, height, x + 1, y + 1),
        _value(pixels, width, height, x, y + 1),
        _value(pixels, width, height, x - 1, y + 1),
        _value(pixels, width, height, x - 1, y),
        _value(pixels, width, height, x - 1, y - 1),
    )


def _zero_to_one_transitions(neighbors: tuple[int, ...]) -> int:
    cycle = neighbors[1:] + neighbors[:1]
    return sum(
        first == 0 and second == 1
        for first, second in zip(neighbors, cycle, strict=True)
    )


def _deletable(
    pixels: bytearray,
    width: int,
    height: int,
    x: int,
    y: int,
    *,
    first_subiteration: bool,
) -> bool:
    if _value(pixels, width, height, x, y) == 0:
        return False

    neighbors = _ordered_neighbors(pixels, width, height, x, y)
    neighbor_count = sum(neighbors)
    if neighbor_count < 2 or neighbor_count > 6:
        return False
    if _zero_to_one_transitions(neighbors) != 1:
        return False

    p2, _, p4, _, p6, _, p8, _ = neighbors
    if first_subiteration:
        return p2 * p4 * p6 == 0 and p4 * p6 * p8 == 0
    return p2 * p4 * p8 == 0 and p2 * p6 * p8 == 0


def zhang_suen_thin(mask: BinaryMask) -> tuple[BinaryMask, int]:
    """Thin a binary foreground mask to a one-pixel skeleton."""

    data, width, height = mask
    pixels = bytearray(1 if value else 0 for value in data)
    iterations = 0

    while True:
        changed = False
        for first_subiteration in (True, False):
            removals: list[int] = []
            for y in range(height):
                for x in range(width):
                    if _deletable(
                        pixels,
                        width,
                        height,
                        x,
                        y,
                        first_subiteration=first_subiteration,
                    ):
                        removals.append(y * width + x)

            if removals:
                changed = True
                for offset in removals:
                    pixels[offset] = 0

        if not changed:
            break
        iterations += 1

    output = bytes(255 if value else 0 for value in pixels)
    return (output, width, height), iterations


def classify_skeleton_pixels(mask: BinaryMask) -> list[SkeletonPixelFeature]:
    """Classify skeleton pixels by 8-neighbor graph degree."""

    data, width, height = mask
    pixels = bytearray(1 if value else 0 for value in data)
    features: list[SkeletonPixelFeature] = []

    for y in range(height):
        for x in range(width):
            if _value(pixels, width, height, x, y) == 0:
                continue
            degree = sum(
                _value(pixels, width, height, x + dx, y + dy)
                for dx, dy in _NEIGHBORS_8
            )
            if degree == 0:
                kind: SkeletonPixelKind = "isolated"
            elif degree == 1:
                kind = "endpoint"
            elif degree == 2:
                kind = "path"
            else:
                kind = "junction"
            features.append(
                SkeletonPixelFeature(
                    x=x,
                    y=y,
                    degree=degree,
                    kind=kind,
                )
            )

    return features



def consolidate_junction_clusters(
    features: list[SkeletonPixelFeature],
) -> list[SkeletonJunctionCluster]:
    """Collapse each 8-connected junction-pixel blob into one deterministic node."""

    skeleton_pixels = {(feature.x, feature.y) for feature in features}
    remaining = {
        (feature.x, feature.y)
        for feature in features
        if feature.kind == "junction"
    }
    clusters: list[SkeletonJunctionCluster] = []

    while remaining:
        seed = min(remaining, key=lambda point: (point[1], point[0]))
        stack = [seed]
        remaining.remove(seed)
        cluster_pixels: set[tuple[int, int]] = set()

        while stack:
            x, y = stack.pop()
            cluster_pixels.add((x, y))
            for dx, dy in _NEIGHBORS_8:
                neighbor = (x + dx, y + dy)
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    stack.append(neighbor)

        ordered_pixels = tuple(
            sorted(cluster_pixels, key=lambda point: (point[1], point[0]))
        )
        centroid_x = sum(x for x, _ in ordered_pixels) / len(ordered_pixels)
        centroid_y = sum(y for _, y in ordered_pixels) / len(ordered_pixels)
        representative_x, representative_y = min(
            ordered_pixels,
            key=lambda point: (
                (point[0] - centroid_x) ** 2 + (point[1] - centroid_y) ** 2,
                point[1],
                point[0],
            ),
        )

        external_connections = {
            (x + dx, y + dy)
            for x, y in ordered_pixels
            for dx, dy in _NEIGHBORS_8
            if (x + dx, y + dy) in skeleton_pixels
            and (x + dx, y + dy) not in cluster_pixels
        }
        clusters.append(
            SkeletonJunctionCluster(
                id="",
                pixels=ordered_pixels,
                centroid_x=centroid_x,
                centroid_y=centroid_y,
                representative_x=representative_x,
                representative_y=representative_y,
                external_connections=tuple(
                    sorted(
                        external_connections,
                        key=lambda point: (point[1], point[0]),
                    )
                ),
            )
        )

    clusters.sort(
        key=lambda cluster: (
            cluster.representative_y,
            cluster.representative_x,
            cluster.centroid_y,
            cluster.centroid_x,
        )
    )
    return [
        SkeletonJunctionCluster(
            id=f"junction-{index:04d}",
            pixels=cluster.pixels,
            centroid_x=cluster.centroid_x,
            centroid_y=cluster.centroid_y,
            representative_x=cluster.representative_x,
            representative_y=cluster.representative_y,
            external_connections=cluster.external_connections,
        )
        for index, cluster in enumerate(clusters, start=1)
    ]



def _edge_key(
    first: tuple[int, int],
    second: tuple[int, int],
) -> tuple[tuple[int, int], tuple[int, int]]:
    return (first, second) if first <= second else (second, first)


def _pixel_adjacency(
    features: list[SkeletonPixelFeature],
) -> dict[tuple[int, int], list[tuple[int, int]]]:
    pixels = {(feature.x, feature.y) for feature in features}
    adjacency: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for x, y in pixels:
        adjacency[(x, y)] = sorted(
            [
                (x + dx, y + dy)
                for dx, dy in _NEIGHBORS_8
                if (x + dx, y + dy) in pixels
            ],
            key=lambda point: (point[1], point[0]),
        )
    return adjacency


def build_initial_branch_graph(
    features: list[SkeletonPixelFeature],
    junction_clusters: list[SkeletonJunctionCluster],
) -> tuple[list[SkeletonGraphNode], list[SkeletonGraphEdge]]:
    """Trace degree-2 paths between endpoints and consolidated junction nodes."""

    if not features:
        return [], []

    feature_by_pixel = {(feature.x, feature.y): feature for feature in features}
    adjacency = _pixel_adjacency(features)
    nodes: list[SkeletonGraphNode] = []
    pixel_to_node: dict[tuple[int, int], str] = {}

    for cluster in junction_clusters:
        node = SkeletonGraphNode(
            id=cluster.id,
            kind="junction",
            x=cluster.centroid_x,
            y=cluster.centroid_y,
            source_pixels=cluster.pixels,
            external_connection_count=len(cluster.external_connections),
        )
        nodes.append(node)
        for pixel in cluster.pixels:
            pixel_to_node[pixel] = node.id

    endpoints = sorted(
        (
            feature
            for feature in features
            if feature.kind == "endpoint"
        ),
        key=lambda feature: (feature.y, feature.x),
    )
    for index, feature in enumerate(endpoints, start=1):
        node_id = f"endpoint-{index:04d}"
        node = SkeletonGraphNode(
            id=node_id,
            kind="endpoint",
            x=float(feature.x),
            y=float(feature.y),
            source_pixels=((feature.x, feature.y),),
            external_connection_count=feature.degree,
        )
        nodes.append(node)
        pixel_to_node[(feature.x, feature.y)] = node_id

    isolated = sorted(
        (
            feature
            for feature in features
            if feature.kind == "isolated"
        ),
        key=lambda feature: (feature.y, feature.x),
    )
    for index, feature in enumerate(isolated, start=1):
        node_id = f"isolated-{index:04d}"
        node = SkeletonGraphNode(
            id=node_id,
            kind="isolated",
            x=float(feature.x),
            y=float(feature.y),
            source_pixels=((feature.x, feature.y),),
            external_connection_count=0,
        )
        nodes.append(node)
        pixel_to_node[(feature.x, feature.y)] = node_id

    if not pixel_to_node:
        anchor = min(feature_by_pixel, key=lambda point: (point[1], point[0]))
        node_id = "cycle-0001"
        node = SkeletonGraphNode(
            id=node_id,
            kind="cycle_anchor",
            x=float(anchor[0]),
            y=float(anchor[1]),
            source_pixels=(anchor,),
            external_connection_count=len(adjacency[anchor]),
        )
        nodes.append(node)
        pixel_to_node[anchor] = node_id

    visited_edges: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    traced: list[
        tuple[
            str,
            str,
            tuple[tuple[int, int], ...],
            float,
            bool,
        ]
    ] = []

    for node in sorted(nodes, key=lambda item: item.id):
        for start_pixel in node.source_pixels:
            for neighbor in adjacency[start_pixel]:
                if pixel_to_node.get(neighbor) == node.id:
                    continue
                first_edge = _edge_key(start_pixel, neighbor)
                if first_edge in visited_edges:
                    continue

                path = [start_pixel, neighbor]
                visited_edges.add(first_edge)
                previous = start_pixel
                current = neighbor

                while current not in pixel_to_node:
                    candidates = [
                        candidate
                        for candidate in adjacency[current]
                        if candidate != previous
                    ]
                    if len(candidates) != 1:
                        raise ValueError(
                            "Skeleton path encountered a non-node pixel "
                            "with an unexpected graph degree"
                        )
                    following = candidates[0]
                    visited_edges.add(_edge_key(current, following))
                    path.append(following)
                    previous, current = current, following

                target_node_id = pixel_to_node[current]
                length = sum(
                    hypot(second[0] - first[0], second[1] - first[1])
                    for first, second in pairwise(path)
                )
                traced.append(
                    (
                        node.id,
                        target_node_id,
                        tuple(path),
                        length,
                        node.id == target_node_id,
                    )
                )

    traced.sort(
        key=lambda item: (
            min(item[0], item[1]),
            max(item[0], item[1]),
            item[2][0][1],
            item[2][0][0],
            item[2][-1][1],
            item[2][-1][0],
        )
    )
    edges = [
        SkeletonGraphEdge(
            id=f"branch-{index:04d}",
            source_node_id=source,
            target_node_id=target,
            pixels=pixels,
            boundary_to_boundary_length_pixels=length,
            is_cycle=is_cycle,
        )
        for index, (source, target, pixels, length, is_cycle) in enumerate(
            traced,
            start=1,
        )
    ]
    return sorted(nodes, key=lambda item: item.id), edges



def prune_terminal_spurs(
    mask: BinaryMask,
    *,
    max_length_pixels: float,
) -> SkeletonPruningResult:
    """Iteratively remove only short endpoint-to-junction terminal branches."""

    if max_length_pixels < 0:
        raise ValueError("Terminal spur threshold cannot be negative")

    data, width, height = mask
    working = bytearray(data)
    removals: list[SkeletonSpurRemoval] = []

    while max_length_pixels > 0:
        current_mask: BinaryMask = (bytes(working), width, height)
        features = classify_skeleton_pixels(current_mask)
        junction_clusters = consolidate_junction_clusters(features)
        nodes, edges = build_initial_branch_graph(features, junction_clusters)
        node_by_id = {node.id: node for node in nodes}

        eligible: list[
            tuple[
                float,
                str,
                SkeletonGraphEdge,
                SkeletonGraphNode,
                SkeletonGraphNode,
            ]
        ] = []
        for edge in edges:
            if edge.is_cycle or edge.boundary_to_boundary_length_pixels > max_length_pixels:
                continue
            source = node_by_id[edge.source_node_id]
            target = node_by_id[edge.target_node_id]
            if source.kind == "endpoint" and target.kind == "junction":
                endpoint, junction = source, target
            elif source.kind == "junction" and target.kind == "endpoint":
                endpoint, junction = target, source
            else:
                continue
            eligible.append(
                (
                    edge.boundary_to_boundary_length_pixels,
                    edge.id,
                    edge,
                    endpoint,
                    junction,
                )
            )

        if not eligible:
            break

        _, _, edge, endpoint, junction = min(
            eligible,
            key=lambda item: (item[0], item[1]),
        )
        protected = set(junction.source_pixels)
        removed = tuple(pixel for pixel in edge.pixels if pixel not in protected)
        if not removed:
            break

        for x, y in removed:
            working[y * width + x] = 0

        removals.append(
            SkeletonSpurRemoval(
                iteration=len(removals) + 1,
                branch_id=edge.id,
                endpoint_x=int(endpoint.x),
                endpoint_y=int(endpoint.y),
                junction_id=junction.id,
                branch_length_pixels=edge.boundary_to_boundary_length_pixels,
                removed_pixels=removed,
            )
        )

    final_mask: BinaryMask = (bytes(working), width, height)
    final_features = classify_skeleton_pixels(final_mask)
    final_clusters = consolidate_junction_clusters(final_features)
    final_nodes, final_edges = build_initial_branch_graph(
        final_features,
        final_clusters,
    )
    return SkeletonPruningResult(
        mask=final_mask,
        removals=tuple(removals),
        graph_nodes=tuple(final_nodes),
        graph_edges=tuple(final_edges),
    )
