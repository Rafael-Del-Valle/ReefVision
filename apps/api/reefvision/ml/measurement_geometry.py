"""Advanced shape, skeleton, branch, surface-area, and calibration measurements."""

from __future__ import annotations

import math
from collections import defaultdict, deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
from PIL import Image

from reefvision.domain.errors import ValidationError
from reefvision.ml.mask_tools import as_binary if False else None

Point = tuple[float, float]
SurfaceMethod = Literal[
    "none",
    "extruded",
    "cylindrical",
    "elliptical_cylinder",
    "pixel_frustum",
]


@dataclass(frozen=True)
class ShapeMeasurements:
    area_pixels: int
    perimeter_pixels: float
    convex_hull_area_pixels: float
    solidity: float
    circularity: float
    compactness: float
    feret_max_pixels: float
    feret_min_pixels: float
    major_axis_pixels: float
    minor_axis_pixels: float
    orientation_degrees: float
    bounding_width_pixels: int
    bounding_height_pixels: int


@dataclass(frozen=True)
class SkeletonMeasurements:
    method: str
    skeleton_pixel_count: int
    total_length_pixels: float
    longest_path_pixels: float
    endpoint_count: int
    junction_count: int
    branch_count: int
    branch_lengths_pixels: tuple[float, ...]
    pruned_pixels: int
    bridged_gaps: int


@dataclass(frozen=True)
class SurfaceAreaEstimate:
    method: SurfaceMethod
    area: float | None
    unit_squared: str | None
    standard_uncertainty: float | None
    lower_95: float | None
    upper_95: float | None
    assumptions: tuple[str, ...]


@dataclass(frozen=True)
class CalibrationEstimate:
    distance_per_pixel: float
    unit: str
    reference_count: int
    residual_standard_error: float | None
    lower_95: float | None
    upper_95: float | None


def binary_mask(values: np.ndarray | Image.Image) -> np.ndarray:
    array = np.asarray(values if isinstance(values, np.ndarray) else values.convert("L"))
    if array.ndim != 2:
        raise ValidationError("Measurements require a two-dimensional mask")
    return array > 0


def _pixel_perimeter(mask: np.ndarray) -> float:
    padded = np.pad(mask, 1, constant_values=False)
    center = padded[1:-1, 1:-1]
    perimeter = (
        (center & ~padded[:-2, 1:-1]).sum()
        + (center & ~padded[2:, 1:-1]).sum()
        + (center & ~padded[1:-1, :-2]).sum()
        + (center & ~padded[1:-1, 2:]).sum()
    )
    return float(perimeter)


def _convex_hull(points: np.ndarray) -> np.ndarray:
    unique = sorted({(float(x), float(y)) for y, x in points})
    if len(unique) <= 2:
        return np.asarray(unique, dtype=np.float64)

    def cross(origin: Point, a: Point, b: Point) -> float:
        return (a[0] - origin[0]) * (b[1] - origin[1]) - (a[1] - origin[1]) * (b[0] - origin[0])

    lower: list[Point] = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[Point] = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return np.asarray([*lower[:-1], *upper[:-1]], dtype=np.float64)


def _polygon_area(points: np.ndarray) -> float:
    if len(points) < 3:
        return 0.0
    x = points[:, 0]
    y = points[:, 1]
    return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2)


def _feret(points: np.ndarray) -> tuple[float, float]:
    if len(points) < 2:
        return 0.0, 0.0
    differences = points[:, None, :] - points[None, :, :]
    maximum = float(np.sqrt(np.max(np.sum(differences * differences, axis=2))))
    minimum = math.inf
    for index in range(len(points)):
        start = points[index]
        end = points[(index + 1) % len(points)]
        edge = end - start
        length = float(np.linalg.norm(edge))
        if length <= 1e-12:
            continue
        normal = np.array([-edge[1], edge[0]]) / length
        projections = points @ normal
        minimum = min(minimum, float(projections.max() - projections.min()))
    return maximum, 0.0 if not math.isfinite(minimum) else minimum


def shape_measurements(values: np.ndarray | Image.Image) -> ShapeMeasurements:
    mask = binary_mask(values)
    coordinates = np.column_stack(np.nonzero(mask))
    if len(coordinates) == 0:
        raise ValidationError("Cannot measure an empty mask")
    area = int(mask.sum())
    perimeter = _pixel_perimeter(mask)
    hull = _convex_hull(coordinates)
    hull_area = _polygon_area(hull)
    feret_max, feret_min = _feret(hull)
    xy = coordinates[:, [1, 0]].astype(np.float64)
    centered = xy - xy.mean(axis=0)
    covariance = np.cov(centered, rowvar=False, bias=True)
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    order = np.argsort(eigenvalues)[::-1]
    eigenvalues = np.maximum(eigenvalues[order], 0)
    eigenvectors = eigenvectors[:, order]
    major = float(4 * math.sqrt(eigenvalues[0])) if len(eigenvalues) else 0.0
    minor = float(4 * math.sqrt(eigenvalues[1])) if len(eigenvalues) > 1 else 0.0
    orientation = float(
        math.degrees(math.atan2(eigenvectors[1, 0], eigenvectors[0, 0]))
    )
    rows, columns = coordinates[:, 0], coordinates[:, 1]
    width = int(columns.max() - columns.min() + 1)
    height = int(rows.max() - rows.min() + 1)
    circularity = 4 * math.pi * area / (perimeter * perimeter) if perimeter else 0.0
    return ShapeMeasurements(
        area_pixels=area,
        perimeter_pixels=perimeter,
        convex_hull_area_pixels=hull_area,
        solidity=area / hull_area if hull_area else 0.0,
        circularity=circularity,
        compactness=(perimeter * perimeter) / area if area else 0.0,
        feret_max_pixels=feret_max,
        feret_min_pixels=feret_min,
        major_axis_pixels=major,
        minor_axis_pixels=minor,
        orientation_degrees=orientation,
        bounding_width_pixels=width,
        bounding_height_pixels=height,
    )


def _neighbor_values(mask: np.ndarray, y: int, x: int) -> list[bool]:
    return [
        bool(mask[y - 1, x]),
        bool(mask[y - 1, x + 1]),
        bool(mask[y, x + 1]),
        bool(mask[y + 1, x + 1]),
        bool(mask[y + 1, x]),
        bool(mask[y + 1, x - 1]),
        bool(mask[y, x - 1]),
        bool(mask[y - 1, x - 1]),
    ]


def skeletonize(values: np.ndarray | Image.Image) -> np.ndarray:
    """Zhang-Suen thinning with deterministic two-subiteration deletion."""

    mask = np.pad(binary_mask(values), 1, constant_values=False)
    changed = True
    while changed:
        changed = False
        for phase in (0, 1):
            remove: list[tuple[int, int]] = []
            for y, x in zip(*np.nonzero(mask), strict=True):
                y, x = int(y), int(x)
                if y in {0, mask.shape[0] - 1} or x in {0, mask.shape[1] - 1}:
                    continue
                neighbors = _neighbor_values(mask, y, x)
                count = sum(neighbors)
                transitions = sum(
                    not neighbors[index] and neighbors[(index + 1) % 8]
                    for index in range(8)
                )
                if not 2 <= count <= 6 or transitions != 1:
                    continue
                north, east, south, west = (
                    neighbors[0],
                    neighbors[2],
                    neighbors[4],
                    neighbors[6],
                )
                if phase == 0:
                    conditions = (north and east and south, east and south and west)
                else:
                    conditions = (north and east and west, north and south and west)
                if not any(conditions):
                    remove.append((y, x))
            if remove:
                changed = True
                for y, x in remove:
                    mask[y, x] = False
    return mask[1:-1, 1:-1]


def _skeleton_neighbors(mask: np.ndarray, node: tuple[int, int]) -> list[tuple[int, int]]:
    y, x = node
    output = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == dx == 0:
                continue
            ny, nx = y + dy, x + dx
            if 0 <= ny < mask.shape[0] and 0 <= nx < mask.shape[1] and mask[ny, nx]:
                output.append((ny, nx))
    return output


def _edge_length(first: tuple[int, int], second: tuple[int, int]) -> float:
    return math.sqrt(2) if first[0] != second[0] and first[1] != second[1] else 1.0


def bridge_skeleton_gaps(skeleton: np.ndarray, *, maximum_gap_pixels: float) -> tuple[np.ndarray, int]:
    if maximum_gap_pixels <= 0:
        return binary_mask(skeleton), 0
    output = binary_mask(skeleton).copy()
    endpoints = [
        (int(y), int(x))
        for y, x in zip(*np.nonzero(output), strict=True)
        if len(_skeleton_neighbors(output, (int(y), int(x)))) == 1
    ]
    bridged = 0
    used: set[tuple[int, int]] = set()
    for endpoint in endpoints:
        if endpoint in used:
            continue
        candidates = [
            other
            for other in endpoints
            if other != endpoint
            and other not in used
            and math.dist(endpoint, other) <= maximum_gap_pixels
        ]
        if not candidates:
            continue
        other = min(candidates, key=lambda candidate: math.dist(endpoint, candidate))
        steps = max(abs(other[0] - endpoint[0]), abs(other[1] - endpoint[1]))
        for index in range(steps + 1):
            fraction = index / max(steps, 1)
            y = round(endpoint[0] + fraction * (other[0] - endpoint[0]))
            x = round(endpoint[1] + fraction * (other[1] - endpoint[1]))
            output[y, x] = True
        used.update((endpoint, other))
        bridged += 1
    return output, bridged


def prune_skeleton_spurs(
    skeleton: np.ndarray,
    *,
    maximum_spur_length_pixels: float,
) -> tuple[np.ndarray, int]:
    output = binary_mask(skeleton).copy()
    removed = 0
    changed = True
    while changed:
        changed = False
        endpoints = [
            (int(y), int(x))
            for y, x in zip(*np.nonzero(output), strict=True)
            if len(_skeleton_neighbors(output, (int(y), int(x)))) == 1
        ]
        for endpoint in endpoints:
            path = [endpoint]
            previous = None
            current = endpoint
            length = 0.0
            while True:
                neighbors = [
                    node
                    for node in _skeleton_neighbors(output, current)
                    if node != previous
                ]
                if len(neighbors) != 1:
                    break
                next_node = neighbors[0]
                length += _edge_length(current, next_node)
                path.append(next_node)
                previous, current = current, next_node
                if len(_skeleton_neighbors(output, current)) != 2:
                    break
            if length <= maximum_spur_length_pixels and len(path) > 1:
                for y, x in path[:-1]:
                    if output[y, x]:
                        output[y, x] = False
                        removed += 1
                changed = True
    return output, removed


def _branch_segments(skeleton: np.ndarray) -> list[list[tuple[int, int]]]:
    nodes = {(int(y), int(x)) for y, x in zip(*np.nonzero(skeleton), strict=True)}
    degrees = {node: len(_skeleton_neighbors(skeleton, node)) for node in nodes}
    terminals = {node for node, degree in degrees.items() if degree != 2}
    visited_edges: set[frozenset[tuple[int, int]]] = set()
    segments: list[list[tuple[int, int]]] = []
    starts = sorted(terminals or nodes)
    for start in starts:
        for neighbor in _skeleton_neighbors(skeleton, start):
            edge = frozenset((start, neighbor))
            if edge in visited_edges:
                continue
            segment = [start]
            previous, current = start, neighbor
            visited_edges.add(edge)
            while True:
                segment.append(current)
                if current in terminals and current != start:
                    break
                options = [
                    node
                    for node in _skeleton_neighbors(skeleton, current)
                    if node != previous
                    and frozenset((current, node)) not in visited_edges
                ]
                if not options:
                    break
                next_node = sorted(options)[0]
                visited_edges.add(frozenset((current, next_node)))
                previous, current = current, next_node
            if len(segment) > 1:
                segments.append(segment)
    return segments


def _path_length(path: Sequence[tuple[int, int]]) -> float:
    return sum(_edge_length(first, second) for first, second in zip(path, path[1:], strict=False))


def _longest_shortest_path(skeleton: np.ndarray) -> float:
    nodes = [(int(y), int(x)) for y, x in zip(*np.nonzero(skeleton), strict=True)]
    endpoints = [node for node in nodes if len(_skeleton_neighbors(skeleton, node)) == 1]
    sources = endpoints or nodes[:1]
    maximum = 0.0
    for source in sources:
        distances = {source: 0.0}
        queue: list[tuple[float, tuple[int, int]]] = [(0.0, source)]
        while queue:
            queue.sort(reverse=True)
            distance, node = queue.pop()
            if distance > distances[node]:
                continue
            for neighbor in _skeleton_neighbors(skeleton, node):
                candidate = distance + _edge_length(node, neighbor)
                if candidate < distances.get(neighbor, math.inf):
                    distances[neighbor] = candidate
                    queue.append((candidate, neighbor))
        maximum = max(maximum, max(distances.values(), default=0.0))
    return maximum


def skeleton_measurements(
    values: np.ndarray | Image.Image,
    *,
    prune_spurs_pixels: float = 0,
    bridge_gaps_pixels: float = 0,
) -> tuple[np.ndarray, SkeletonMeasurements]:
    skeleton = skeletonize(values)
    skeleton, bridged = bridge_skeleton_gaps(
        skeleton,
        maximum_gap_pixels=bridge_gaps_pixels,
    )
    skeleton, pruned = prune_skeleton_spurs(
        skeleton,
        maximum_spur_length_pixels=prune_spurs_pixels,
    )
    nodes = [(int(y), int(x)) for y, x in zip(*np.nonzero(skeleton), strict=True)]
    degrees = [len(_skeleton_neighbors(skeleton, node)) for node in nodes]
    segments = _branch_segments(skeleton)
    lengths = tuple(_path_length(segment) for segment in segments)
    return skeleton, SkeletonMeasurements(
        method="zhang_suen_8_neighbor_graph",
        skeleton_pixel_count=len(nodes),
        total_length_pixels=sum(lengths),
        longest_path_pixels=_longest_shortest_path(skeleton),
        endpoint_count=sum(degree == 1 for degree in degrees),
        junction_count=sum(degree >= 3 for degree in degrees),
        branch_count=len(segments),
        branch_lengths_pixels=lengths,
        pruned_pixels=pruned,
        bridged_gaps=bridged,
    )


def calibrate_references(
    references: Sequence[tuple[float, float]],
    *,
    unit: str,
) -> CalibrationEstimate:
    """Fit physical distance = scale × pixel distance through the origin."""

    if not references:
        raise ValidationError("At least one calibration reference is required")
    pixels = np.asarray([item[0] for item in references], dtype=np.float64)
    physical = np.asarray([item[1] for item in references], dtype=np.float64)
    if np.any(pixels <= 0) or np.any(physical <= 0):
        raise ValidationError("Calibration distances must be positive")
    denominator = float(np.dot(pixels, pixels))
    scale = float(np.dot(pixels, physical) / denominator)
    residuals = physical - scale * pixels
    standard_error = None
    lower = upper = None
    if len(references) > 1:
        residual_variance = float(np.dot(residuals, residuals) / (len(references) - 1))
        standard_error = math.sqrt(residual_variance / denominator)
        lower = max(0.0, scale - 1.96 * standard_error)
        upper = scale + 1.96 * standard_error
    return CalibrationEstimate(
        distance_per_pixel=scale,
        unit=unit.strip(),
        reference_count=len(references),
        residual_standard_error=standard_error,
        lower_95=lower,
        upper_95=upper,
    )


def surface_area_estimate(
    *,
    method: SurfaceMethod,
    projected_area: float,
    perimeter: float,
    centerline_length: float,
    depth: float | None = None,
    diameter_major: float | None = None,
    diameter_minor: float | None = None,
    pixel_area_scale: float | None = None,
    uncertainty_fraction: float | None = None,
    unit: str | None = None,
) -> SurfaceAreaEstimate:
    assumptions: list[str] = []
    area: float | None
    if method == "none":
        area = None
    elif method == "extruded":
        if depth is None or depth <= 0:
            raise ValidationError("Extruded surface area requires a positive depth")
        area = 2 * projected_area + perimeter * depth
        assumptions.append("Closed prism with constant extrusion depth")
    elif method == "cylindrical":
        if diameter_major is None or diameter_major <= 0:
            raise ValidationError("Cylindrical surface area requires a positive diameter")
        area = math.pi * diameter_major * centerline_length
        assumptions.append("Circular branch cross section with constant diameter")
    elif method == "elliptical_cylinder":
        if (
            diameter_major is None
            or diameter_minor is None
            or diameter_major <= 0
            or diameter_minor <= 0
        ):
            raise ValidationError("Elliptical surface area requires two positive diameters")
        a = diameter_major / 2
        b = diameter_minor / 2
        circumference = math.pi * (3 * (a + b) - math.sqrt((3 * a + b) * (a + 3 * b)))
        area = circumference * centerline_length
        assumptions.append("Elliptical branch cross section with constant diameters")
    elif method == "pixel_frustum":
        if pixel_area_scale is None or pixel_area_scale <= 0:
            raise ValidationError("Pixel-frustum surface area requires a positive pixel scale")
        area = projected_area * pixel_area_scale
        assumptions.append("Locally fronto-parallel depth projection")
    else:
        raise ValidationError("Unknown surface-area method")
    standard_uncertainty = lower = upper = None
    if area is not None and uncertainty_fraction is not None:
        if uncertainty_fraction < 0:
            raise ValidationError("Surface-area uncertainty cannot be negative")
        standard_uncertainty = area * uncertainty_fraction
        lower = max(0.0, area - 1.96 * standard_uncertainty)
        upper = area + 1.96 * standard_uncertainty
    return SurfaceAreaEstimate(
        method=method,
        area=area,
        unit_squared=f"{unit}²" if unit else None,
        standard_uncertainty=standard_uncertainty,
        lower_95=lower,
        upper_95=upper,
        assumptions=tuple(assumptions),
    )
