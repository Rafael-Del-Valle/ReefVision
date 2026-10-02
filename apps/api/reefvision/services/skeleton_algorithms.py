"""Topology-preserving binary skeleton algorithms for coral structure analysis."""

from __future__ import annotations

from dataclasses import dataclass
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
