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
