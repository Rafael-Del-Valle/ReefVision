"""Provider-free polygon, raster morphology, conversion, and annotation-QA tools."""

from __future__ import annotations

import math
from collections import defaultdict, deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal, TypeAlias

import numpy as np
from PIL import Image, ImageDraw

from reefvision.domain.errors import ValidationError

Point: TypeAlias = tuple[float, float]
Ring: TypeAlias = list[Point]
BooleanOperation = Literal["union", "intersection", "subtract", "xor"]


@dataclass(frozen=True)
class PolygonQuality:
    area: float
    perimeter: float
    orientation: str
    self_intersections: tuple[tuple[int, int], ...]
    outside_vertex_count: int
    touches_boundary: bool
    vertex_count: int


@dataclass(frozen=True)
class RasterQuality:
    area_pixels: int
    component_count: int
    hole_count: int
    touches_boundary: bool
    bounds: tuple[int, int, int, int] | None


def _mask(values: np.ndarray | Image.Image) -> np.ndarray:
    array = np.asarray(values if isinstance(values, np.ndarray) else values.convert("L"))
    if array.ndim != 2:
        raise ValidationError("Mask operations require a two-dimensional raster")
    return np.asarray(array > 0, dtype=bool)


def signed_area(points: Sequence[Point]) -> float:
    if len(points) < 3:
        return 0.0
    return 0.5 * sum(
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in zip(points, (*points[1:], points[0]), strict=True)
    )


def polygon_area(points: Sequence[Point]) -> float:
    return abs(signed_area(points))


def polygon_perimeter(points: Sequence[Point]) -> float:
    if len(points) < 2:
        return 0.0
    return sum(
        math.hypot(x2 - x1, y2 - y1)
        for (x1, y1), (x2, y2) in zip(points, (*points[1:], points[0]), strict=True)
    )


def normalize_ring(
    points: Iterable[Point],
    *,
    clockwise: bool | None = None,
    close: bool = False,
) -> Ring:
    cleaned: Ring = []
    for raw_x, raw_y in points:
        point = (float(raw_x), float(raw_y))
        if not all(math.isfinite(value) for value in point):
            raise ValidationError("Polygon coordinates must be finite")
        if not cleaned or point != cleaned[-1]:
            cleaned.append(point)
    if len(cleaned) > 1 and cleaned[0] == cleaned[-1]:
        cleaned.pop()
    if len(cleaned) < 3:
        raise ValidationError("Polygon rings require at least three distinct vertices")
    area = signed_area(cleaned)
    if math.isclose(area, 0.0, abs_tol=1e-12):
        raise ValidationError("Polygon ring has zero area")
    if clockwise is not None and (area < 0) != clockwise:
        cleaned.reverse()
    if close:
        cleaned.append(cleaned[0])
    return cleaned


def densify_ring(points: Sequence[Point], *, maximum_segment_length: float) -> Ring:
    if maximum_segment_length <= 0:
        raise ValidationError("maximum_segment_length must be positive")
    ring = normalize_ring(points)
    result: Ring = []
    for start, end in zip(ring, (*ring[1:], ring[0]), strict=True):
        result.append(start)
        distance = math.dist(start, end)
        pieces = max(1, math.ceil(distance / maximum_segment_length))
        for index in range(1, pieces):
            fraction = index / pieces
            result.append(
                (
                    start[0] + fraction * (end[0] - start[0]),
                    start[1] + fraction * (end[1] - start[1]),
                )
            )
    return result


def _point_line_distance(point: Point, start: Point, end: Point) -> float:
    if start == end:
        return math.dist(point, start)
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    numerator = abs(dy * point[0] - dx * point[1] + end[0] * start[1] - end[1] * start[0])
    return numerator / math.hypot(dx, dy)


def _rdp(points: Sequence[Point], tolerance: float) -> Ring:
    if len(points) <= 2:
        return list(points)
    start, end = points[0], points[-1]
    distances = [_point_line_distance(point, start, end) for point in points[1:-1]]
    if not distances or max(distances) <= tolerance:
        return [start, end]
    index = distances.index(max(distances)) + 1
    return [*_rdp(points[: index + 1], tolerance)[:-1], *_rdp(points[index:], tolerance)]


def simplify_ring(points: Sequence[Point], *, tolerance: float) -> Ring:
    if tolerance < 0:
        raise ValidationError("Polygon simplification tolerance cannot be negative")
    ring = normalize_ring(points)
    if tolerance == 0:
        return ring
    anchor = min(range(len(ring)), key=lambda index: (ring[index][0], ring[index][1]))
    rotated = [*ring[anchor:], *ring[:anchor], ring[anchor]]
    simplified = _rdp(rotated, tolerance)
    if simplified and simplified[-1] == simplified[0]:
        simplified.pop()
    return normalize_ring(simplified)


def _orientation(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a: Point, b: Point, p: Point, epsilon: float = 1e-9) -> bool:
    return (
        min(a[0], b[0]) - epsilon <= p[0] <= max(a[0], b[0]) + epsilon
        and min(a[1], b[1]) - epsilon <= p[1] <= max(a[1], b[1]) + epsilon
        and abs(_orientation(a, b, p)) <= epsilon
    )


def segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    ab_c, ab_d = _orientation(a, b, c), _orientation(a, b, d)
    cd_a, cd_b = _orientation(c, d, a), _orientation(c, d, b)
    if (ab_c > 0 > ab_d or ab_d > 0 > ab_c) and (cd_a > 0 > cd_b or cd_b > 0 > cd_a):
        return True
    return any(
        (
            abs(value) <= 1e-9 and _on_segment(start, end, point)
            for value, start, end, point in (
                (ab_c, a, b, c),
                (ab_d, a, b, d),
                (cd_a, c, d, a),
                (cd_b, c, d, b),
            )
        )
    )


def self_intersections(points: Sequence[Point]) -> list[tuple[int, int]]:
    ring = normalize_ring(points)
    edges = list(zip(ring, (*ring[1:], ring[0]), strict=True))
    intersections: list[tuple[int, int]] = []
    for first_index, (a, b) in enumerate(edges):
        for second_index in range(first_index + 1, len(edges)):
            if second_index in {first_index, first_index + 1}:
                continue
            if first_index == 0 and second_index == len(edges) - 1:
                continue
            c, d = edges[second_index]
            if segments_intersect(a, b, c, d):
                intersections.append((first_index, second_index))
    return intersections


def convex_hull(points: Iterable[Point]) -> Ring:
    unique = sorted({(float(x), float(y)) for x, y in points})
    if len(unique) < 3:
        raise ValidationError("Convex-hull repair requires at least three distinct points")

    def cross(origin: Point, a: Point, b: Point) -> float:
        return (a[0] - origin[0]) * (b[1] - origin[1]) - (a[1] - origin[1]) * (b[0] - origin[0])

    lower: Ring = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: Ring = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return normalize_ring([*lower[:-1], *upper[:-1]])


def snap_ring(
    points: Sequence[Point],
    *,
    width: int,
    height: int,
    edge_distance: float = 4,
    candidates: Sequence[Point] = (),
    candidate_distance: float = 4,
) -> Ring:
    ring = normalize_ring(points)
    output: Ring = []
    for x, y in ring:
        if abs(x) <= edge_distance:
            x = 0.0
        elif abs(x - width) <= edge_distance:
            x = float(width)
        if abs(y) <= edge_distance:
            y = 0.0
        elif abs(y - height) <= edge_distance:
            y = float(height)
        if candidates:
            nearest = min(candidates, key=lambda point: math.dist((x, y), point))
            if math.dist((x, y), nearest) <= candidate_distance:
                x, y = nearest
        output.append((x, y))
    return normalize_ring(output)


def polygon_quality(points: Sequence[Point], *, width: int, height: int) -> PolygonQuality:
    ring = normalize_ring(points)
    area = signed_area(ring)
    outside = sum(not (0 <= x <= width and 0 <= y <= height) for x, y in ring)
    touches = any(x in {0, width} or y in {0, height} for x, y in ring)
    return PolygonQuality(
        area=abs(area),
        perimeter=polygon_perimeter(ring),
        orientation="clockwise" if area < 0 else "counterclockwise",
        self_intersections=tuple(self_intersections(ring)),
        outside_vertex_count=outside,
        touches_boundary=touches,
        vertex_count=len(ring),
    )


def polygon_to_mask(
    outer: Sequence[Point],
    *,
    width: int,
    height: int,
    holes: Sequence[Sequence[Point]] = (),
) -> np.ndarray:
    image = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(image)
    draw.polygon(normalize_ring(outer), fill=255)
    for hole in holes:
        draw.polygon(normalize_ring(hole), fill=0)
    return np.asarray(image, dtype=np.uint8) > 0


def _neighbors(y: int, x: int, height: int, width: int, connectivity: int) -> Iterable[tuple[int, int]]:
    offsets = ((-1, 0), (1, 0), (0, -1), (0, 1))
    if connectivity == 8:
        offsets = (*offsets, (-1, -1), (-1, 1), (1, -1), (1, 1))
    for dy, dx in offsets:
        ny, nx = y + dy, x + dx
        if 0 <= ny < height and 0 <= nx < width:
            yield ny, nx


def connected_components(
    values: np.ndarray | Image.Image,
    *,
    connectivity: int = 8,
) -> list[np.ndarray]:
    if connectivity not in {4, 8}:
        raise ValidationError("Connectivity must be four or eight")
    mask = _mask(values)
    height, width = mask.shape
    visited = np.zeros(mask.shape, dtype=bool)
    components: list[np.ndarray] = []
    for y, x in zip(*np.nonzero(mask), strict=True):
        if visited[y, x]:
            continue
        component = np.zeros(mask.shape, dtype=bool)
        queue = [(int(y), int(x))]
        visited[y, x] = True
        while queue:
            cy, cx = queue.pop()
            component[cy, cx] = True
            for ny, nx in _neighbors(cy, cx, height, width, connectivity):
                if mask[ny, nx] and not visited[ny, nx]:
                    visited[ny, nx] = True
                    queue.append((ny, nx))
        components.append(component)
    return components


def _shift(mask: np.ndarray, dy: int, dx: int, *, fill: bool) -> np.ndarray:
    height, width = mask.shape
    result = np.full(mask.shape, fill, dtype=bool)
    source_y = slice(max(0, -dy), min(height, height - dy))
    source_x = slice(max(0, -dx), min(width, width - dx))
    target_y = slice(max(0, dy), min(height, height + dy))
    target_x = slice(max(0, dx), min(width, width + dx))
    result[target_y, target_x] = mask[source_y, source_x]
    return result


def _disk_offsets(radius: int) -> list[tuple[int, int]]:
    if radius < 1:
        raise ValidationError("Morphology radius must be at least one pixel")
    return [
        (dy, dx)
        for dy in range(-radius, radius + 1)
        for dx in range(-radius, radius + 1)
        if dx * dx + dy * dy <= radius * radius
    ]


def dilate(values: np.ndarray | Image.Image, *, radius: int = 1) -> np.ndarray:
    mask = _mask(values)
    result = np.zeros(mask.shape, dtype=bool)
    for dy, dx in _disk_offsets(radius):
        result |= _shift(mask, dy, dx, fill=False)
    return result


def erode(values: np.ndarray | Image.Image, *, radius: int = 1) -> np.ndarray:
    mask = _mask(values)
    result = np.ones(mask.shape, dtype=bool)
    for dy, dx in _disk_offsets(radius):
        result &= _shift(mask, dy, dx, fill=False)
    return result


def opening(values: np.ndarray | Image.Image, *, radius: int = 1) -> np.ndarray:
    return dilate(erode(values, radius=radius), radius=radius)


def closing(values: np.ndarray | Image.Image, *, radius: int = 1) -> np.ndarray:
    return erode(dilate(values, radius=radius), radius=radius)


def fill_holes(values: np.ndarray | Image.Image, *, maximum_area: int | None = None) -> np.ndarray:
    mask = _mask(values)
    inverse = ~mask
    height, width = mask.shape
    exterior = np.zeros(mask.shape, dtype=bool)
    queue: deque[tuple[int, int]] = deque()
    for y in range(height):
        for x in (0, width - 1):
            if inverse[y, x] and not exterior[y, x]:
                exterior[y, x] = True
                queue.append((y, x))
    for x in range(width):
        for y in (0, height - 1):
            if inverse[y, x] and not exterior[y, x]:
                exterior[y, x] = True
                queue.append((y, x))
    while queue:
        y, x = queue.popleft()
        for ny, nx in _neighbors(y, x, height, width, 4):
            if inverse[ny, nx] and not exterior[ny, nx]:
                exterior[ny, nx] = True
                queue.append((ny, nx))
    holes = inverse & ~exterior
    if maximum_area is None:
        return mask | holes
    result = mask.copy()
    for component in connected_components(holes, connectivity=4):
        if int(component.sum()) <= maximum_area:
            result |= component
    return result


def remove_small_components(
    values: np.ndarray | Image.Image,
    *,
    minimum_area: int,
    connectivity: int = 8,
    keep_largest: bool = False,
) -> np.ndarray:
    if minimum_area < 1:
        raise ValidationError("minimum_area must be at least one")
    components = connected_components(values, connectivity=connectivity)
    if keep_largest and components:
        components = [max(components, key=lambda component: int(component.sum()))]
    return np.logical_or.reduce(
        [component for component in components if int(component.sum()) >= minimum_area],
        initial=np.zeros(_mask(values).shape, dtype=bool),
    )


def flood_select(
    image: np.ndarray,
    *,
    seed_x: int,
    seed_y: int,
    tolerance: float,
    connectivity: int = 8,
) -> np.ndarray:
    array = np.asarray(image, dtype=np.float32)
    if array.ndim not in {2, 3}:
        raise ValidationError("Flood selection requires grayscale or multichannel image data")
    height, width = array.shape[:2]
    if not (0 <= seed_x < width and 0 <= seed_y < height):
        raise ValidationError("Flood-selection seed lies outside the image")
    reference = array[seed_y, seed_x]
    difference = np.abs(array - reference)
    distance = difference if array.ndim == 2 else np.linalg.norm(difference, axis=2)
    eligible = distance <= tolerance
    selected = np.zeros((height, width), dtype=bool)
    stack = [(seed_y, seed_x)]
    selected[seed_y, seed_x] = True
    while stack:
        y, x = stack.pop()
        for ny, nx in _neighbors(y, x, height, width, connectivity):
            if eligible[ny, nx] and not selected[ny, nx]:
                selected[ny, nx] = True
                stack.append((ny, nx))
    return selected


def boolean_masks(
    first: np.ndarray | Image.Image,
    second: np.ndarray | Image.Image,
    *,
    operation: BooleanOperation,
) -> np.ndarray:
    a, b = _mask(first), _mask(second)
    if a.shape != b.shape:
        raise ValidationError("Boolean mask operands must share dimensions")
    if operation == "union":
        return a | b
    if operation == "intersection":
        return a & b
    if operation == "subtract":
        return a & ~b
    if operation == "xor":
        return a ^ b
    raise ValidationError("Unsupported boolean mask operation")


def _boundary_edges(mask: np.ndarray) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    height, width = mask.shape
    edges: list[tuple[tuple[int, int], tuple[int, int]]] = []
    for y, x in zip(*np.nonzero(mask), strict=True):
        y, x = int(y), int(x)
        if y == 0 or not mask[y - 1, x]:
            edges.append(((x, y), (x + 1, y)))
        if x == width - 1 or not mask[y, x + 1]:
            edges.append(((x + 1, y), (x + 1, y + 1)))
        if y == height - 1 or not mask[y + 1, x]:
            edges.append(((x + 1, y + 1), (x, y + 1)))
        if x == 0 or not mask[y, x - 1]:
            edges.append(((x, y + 1), (x, y)))
    return edges


def _remove_collinear(points: Ring) -> Ring:
    if len(points) < 4:
        return points
    output: Ring = []
    for index, point in enumerate(points):
        before = points[index - 1]
        after = points[(index + 1) % len(points)]
        if abs(_orientation(before, point, after)) > 1e-9:
            output.append(point)
    return output if len(output) >= 3 else points


def mask_to_rings(values: np.ndarray | Image.Image) -> list[Ring]:
    mask = _mask(values)
    outgoing: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    for start, end in _boundary_edges(mask):
        outgoing[start].append(end)
    rings: list[Ring] = []
    while outgoing:
        start = min(outgoing)
        current = start
        raw: Ring = []
        while True:
            raw.append((float(current[0]), float(current[1])))
            options = outgoing.get(current)
            if not options:
                break
            next_point = options.pop()
            if not options:
                del outgoing[current]
            current = next_point
            if current == start:
                break
        if current == start and len(raw) >= 3:
            rings.append(normalize_ring(_remove_collinear(raw)))
    return sorted(rings, key=lambda ring: abs(signed_area(ring)), reverse=True)


def raster_quality(
    values: np.ndarray | Image.Image,
    *,
    connectivity: int = 8,
) -> RasterQuality:
    mask = _mask(values)
    rows, columns = np.nonzero(mask)
    bounds = None
    if rows.size:
        bounds = (
            int(columns.min()),
            int(rows.min()),
            int(columns.max()) + 1,
            int(rows.max()) + 1,
        )
    filled = fill_holes(mask)
    holes = filled & ~mask
    height, width = mask.shape
    touches = bool(
        rows.size
        and (
            np.any(rows == 0)
            or np.any(columns == 0)
            or np.any(rows == height - 1)
            or np.any(columns == width - 1)
        )
    )
    return RasterQuality(
        area_pixels=int(mask.sum()),
        component_count=len(connected_components(mask, connectivity=connectivity)),
        hole_count=len(connected_components(holes, connectivity=4)),
        touches_boundary=touches,
        bounds=bounds,
    )


def mask_iou(first: np.ndarray | Image.Image, second: np.ndarray | Image.Image) -> float:
    a, b = _mask(first), _mask(second)
    if a.shape != b.shape:
        raise ValidationError("Mask IoU operands must share dimensions")
    union = int((a | b).sum())
    return int((a & b).sum()) / union if union else 1.0
