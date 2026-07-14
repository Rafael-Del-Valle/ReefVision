"""Scientific measurement helpers for masks and coral-polyp annotations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

import networkx as nx
import numpy as np
import numpy.typing as npt
from skimage.morphology import skeletonize

BoolArray = npt.NDArray[np.bool_]
FloatArray = npt.NDArray[np.float64]
AnyArray = npt.NDArray[Any]


@dataclass(frozen=True)
class MeasurementResult:
    """A numeric measurement with units and provenance metadata."""

    value: float
    unit: str
    method: str
    metadata: dict[str, Any]


def _as_bool_mask(mask: AnyArray) -> BoolArray:
    return np.asarray(mask, dtype=np.bool_)


def mask_area_pixels(mask: AnyArray) -> MeasurementResult:
    """Return the foreground area of a binary mask in pixels."""

    bool_mask = _as_bool_mask(mask)
    return MeasurementResult(
        value=float(np.count_nonzero(bool_mask)),
        unit="px^2",
        method="foreground_pixel_count",
        metadata={},
    )


def projected_surface_area(mask: AnyArray, mm_per_pixel: float | None = None) -> MeasurementResult:
    """Estimate projected 2D surface area from a binary mask."""

    pixel_area = float(np.count_nonzero(_as_bool_mask(mask)))
    if mm_per_pixel is None:
        return MeasurementResult(
            value=pixel_area,
            unit="px^2",
            method="projected_mask_area",
            metadata={"mm_per_pixel": None},
        )

    return MeasurementResult(
        value=pixel_area * mm_per_pixel * mm_per_pixel,
        unit="mm^2",
        method="projected_mask_area",
        metadata={"mm_per_pixel": mm_per_pixel},
    )


def tle_centerline_length(mask: AnyArray, mm_per_pixel: float | None = None) -> MeasurementResult:
    """Estimate total linear extent from the longest skeleton geodesic."""

    bool_mask = _as_bool_mask(mask)
    typed_skeletonize = cast(Callable[[BoolArray], BoolArray], skeletonize)
    skeleton = typed_skeletonize(bool_mask)
    points = np.argwhere(skeleton)

    if len(points) < 2:
        return MeasurementResult(
            value=0.0,
            unit="px" if mm_per_pixel is None else "mm",
            method="skeleton_geodesic_diameter",
            metadata={"nodes": len(points), "mm_per_pixel": mm_per_pixel},
        )

    graph: nx.Graph[tuple[int, int]] = nx.Graph()
    point_set = {(int(row), int(col)) for row, col in points}

    for row, col in point_set:
        graph.add_node((row, col))
        for d_row in (-1, 0, 1):
            for d_col in (-1, 0, 1):
                if d_row == 0 and d_col == 0:
                    continue
                neighbor = (row + d_row, col + d_col)
                if neighbor in point_set:
                    weight = float(np.hypot(d_row, d_col))
                    graph.add_edge((row, col), neighbor, weight=weight)

    longest = 0.0
    for component in nx.connected_components(graph):
        subgraph = graph.subgraph(component)
        if subgraph.number_of_nodes() < 2:
            continue
        start = next(iter(component))
        distances = nx.single_source_dijkstra_path_length(subgraph, start, weight="weight")
        if not distances:
            continue
        farthest = max(distances, key=lambda point: distances[point])
        diameter_distances = nx.single_source_dijkstra_path_length(
            subgraph,
            farthest,
            weight="weight",
        )
        if diameter_distances:
            longest = max(longest, float(max(diameter_distances.values())))

    if mm_per_pixel is None:
        return MeasurementResult(
            value=longest,
            unit="px",
            method="skeleton_geodesic_diameter",
            metadata={"nodes": len(points), "mm_per_pixel": None},
        )

    return MeasurementResult(
        value=longest * mm_per_pixel,
        unit="mm",
        method="skeleton_geodesic_diameter",
        metadata={"nodes": len(points), "mm_per_pixel": mm_per_pixel},
    )


def depth_aware_surface_area(
    mask: AnyArray,
    depth_map: AnyArray,
    mm_per_pixel: float,
) -> MeasurementResult:
    """Approximate depth-aware surface area from local depth gradients."""

    bool_mask = _as_bool_mask(mask)
    depth = np.asarray(depth_map, dtype=np.float64)
    gradient_y, gradient_x = np.gradient(depth)
    local_scale = np.sqrt(1.0 + gradient_x**2 + gradient_y**2)
    area = float(np.sum(local_scale[bool_mask]) * mm_per_pixel * mm_per_pixel)

    return MeasurementResult(
        value=area,
        unit="mm^2",
        method="depth_gradient_surface_area",
        metadata={"mm_per_pixel": mm_per_pixel},
    )


def polyp_density(polyp_count: int, area: MeasurementResult) -> MeasurementResult:
    """Calculate polyp density from a count and area measurement."""

    if area.value <= 0:
        return MeasurementResult(
            value=0.0,
            unit=f"polyps/{area.unit}",
            method="polyp_count_per_area",
            metadata={"area_method": area.method, "polyp_count": polyp_count},
        )

    return MeasurementResult(
        value=float(polyp_count) / area.value,
        unit=f"polyps/{area.unit}",
        method="polyp_count_per_area",
        metadata={"area_method": area.method, "polyp_count": polyp_count},
    )
