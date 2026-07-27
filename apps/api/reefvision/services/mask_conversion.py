"""Provider-free raster/polygon conversion with multipart and hole preservation."""

from __future__ import annotations

import base64
import io
import math
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from reefvision.domain.errors import ValidationError
from reefvision.ml.mask_tools import (
    connected_components,
    mask_iou,
    mask_to_rings,
    normalize_ring,
    raster_quality,
    remove_small_components,
    self_intersections,
    simplify_ring,
)
from reefvision.schemas.geometry_tools import GeometryPoint, PolygonGeometry
from reefvision.schemas.mask_conversion import (
    MaskConversionQuality,
    PolygonRepairRequest,
    PolygonRepairResponse,
    PolygonToRasterRequest,
    PolygonToRasterResponse,
    RasterToPolygonRequest,
    RasterToPolygonResponse,
    UncompressedMaskRle,
)

_MAX_CONVERSION_PIXELS = 25_000_000


def _check_dimensions(width: int, height: int) -> None:
    if width * height > _MAX_CONVERSION_PIXELS:
        raise ValidationError(
            f"Conversion previews are limited to {_MAX_CONVERSION_PIXELS:,} pixels"
        )


def decode_uncompressed_rle(rle: UncompressedMaskRle) -> NDArray[np.bool_]:
    _check_dimensions(rle.width, rle.height)
    flat = np.zeros(rle.width * rle.height, dtype=np.bool_)
    cursor = 0
    foreground = False
    for count in rle.counts:
        end = cursor + count
        if foreground and count:
            flat[cursor:end] = True
        cursor = end
        foreground = not foreground
    order = "C" if rle.order == "row_major" else "F"
    return flat.reshape(rle.height, rle.width, order=order)


def encode_uncompressed_rle(
    values: NDArray[Any],
    *,
    order: str,
) -> UncompressedMaskRle:
    mask = np.asarray(values, dtype=np.bool_)
    if mask.ndim != 2:
        raise ValidationError("RLE encoding requires a two-dimensional mask")
    height, width = mask.shape
    _check_dimensions(width, height)
    flat = mask.reshape(-1, order="C" if order == "row_major" else "F")
    counts: list[int] = []
    current = False
    run = 0
    for raw in flat:
        value = bool(raw)
        if value == current:
            run += 1
        else:
            counts.append(run)
            run = 1
            current = value
    counts.append(run)
    return UncompressedMaskRle(
        width=width,
        height=height,
        counts=counts,
        order=order,
    )


def _ring(points: list[GeometryPoint]) -> list[tuple[float, float]]:
    return [(float(point.x), float(point.y)) for point in points]


def _schema_ring(points: list[tuple[float, float]]) -> list[GeometryPoint]:
    return [GeometryPoint(x=x, y=y) for x, y in points]


def _fill_ring(
    mask: NDArray[np.bool_],
    points: list[tuple[float, float]],
    *,
    value: bool,
) -> None:
    """Fill one ring using even-odd scanlines sampled at pixel centers.

    Raster-derived contours describe pixel edges. Sampling each pixel at its center
    avoids the inclusive endpoint expansion produced by ``ImageDraw.polygon`` and
    also permits self-crossing, zero-net-area rings to reach the repair workflow.
    """

    ring = normalize_ring(points, allow_zero_area=True)
    edges = list(zip(ring, (*ring[1:], ring[0]), strict=True))
    height, width = mask.shape
    for y in range(height):
        scan_y = y + 0.5
        intersections: list[float] = []
        for (x1, y1), (x2, y2) in edges:
            if (y1 > scan_y) == (y2 > scan_y):
                continue
            intersections.append(x1 + (scan_y - y1) * (x2 - x1) / (y2 - y1))
        intersections.sort()
        for left, right in zip(
            intersections[::2],
            intersections[1::2],
            strict=False,
        ):
            start = max(0, math.ceil(min(left, right) - 0.5))
            stop = min(width, math.ceil(max(left, right) - 0.5))
            if stop > start:
                mask[y, start:stop] = value


def _polygon_mask(
    polygons: list[PolygonGeometry],
    *,
    width: int,
    height: int,
) -> NDArray[np.bool_]:
    _check_dimensions(width, height)
    result = np.zeros((height, width), dtype=np.bool_)
    for polygon in polygons:
        current = np.zeros((height, width), dtype=np.bool_)
        _fill_ring(current, _ring(polygon.outer), value=True)
        for hole in polygon.holes:
            _fill_ring(current, _ring(hole), value=False)
        result |= current
    return result


def _simplified(
    ring: list[tuple[float, float]],
    tolerance: float,
    *,
    clockwise: bool,
    warnings: list[str],
) -> list[tuple[float, float]]:
    try:
        converted = simplify_ring(ring, tolerance=tolerance) if tolerance else ring
        return normalize_ring(converted, clockwise=clockwise)
    except ValidationError as exc:
        warnings.append(f"A ring could not be simplified and was preserved: {exc}")
        return normalize_ring(ring, clockwise=clockwise)


def _vectorize(
    mask: NDArray[Any],
    *,
    simplify_tolerance: float,
    minimum_component_area: int,
    preserve_holes: bool,
) -> tuple[list[PolygonGeometry], NDArray[np.bool_], list[str]]:
    warnings: list[str] = []
    cleaned = remove_small_components(
        np.asarray(mask, dtype=np.bool_),
        minimum_area=minimum_component_area,
        connectivity=8,
    )
    polygons: list[PolygonGeometry] = []
    for component in connected_components(cleaned, connectivity=8):
        rings = mask_to_rings(component)
        if not rings:
            continue
        outer = _simplified(
            rings[0],
            simplify_tolerance,
            clockwise=True,
            warnings=warnings,
        )
        holes: list[list[tuple[float, float]]] = []
        if preserve_holes:
            for ring in rings[1:]:
                holes.append(
                    _simplified(
                        ring,
                        simplify_tolerance,
                        clockwise=False,
                        warnings=warnings,
                    )
                )
        elif len(rings) > 1:
            warnings.append(
                f"Discarded {len(rings) - 1} raster holes because preserve_holes is false."
            )
        polygons.append(
            PolygonGeometry(
                outer=_schema_ring(outer),
                holes=[_schema_ring(hole) for hole in holes],
            )
        )
    polygons.sort(
        key=lambda polygon: (
            min(point.x for point in polygon.outer),
            min(point.y for point in polygon.outer),
        )
    )
    return polygons, np.asarray(cleaned, dtype=np.bool_), warnings


def _quality(values: NDArray[Any]) -> MaskConversionQuality:
    quality = raster_quality(values)
    return MaskConversionQuality(
        foreground_pixels=quality.area_pixels,
        component_count=quality.component_count,
        hole_count=quality.hole_count,
        touches_boundary=quality.touches_boundary,
        bounds=quality.bounds,
    )


def _preview(values: NDArray[Any]) -> str:
    image = Image.fromarray(np.asarray(values, dtype=np.uint8) * 255, mode="L")
    stream = io.BytesIO()
    image.save(stream, format="PNG", optimize=True)
    return base64.b64encode(stream.getvalue()).decode("ascii")


class MaskConversionService:
    def raster_to_polygons(
        self,
        request: RasterToPolygonRequest,
    ) -> RasterToPolygonResponse:
        source = decode_uncompressed_rle(request.raster)
        polygons, cleaned, warnings = _vectorize(
            source,
            simplify_tolerance=request.simplify_tolerance,
            minimum_component_area=request.minimum_component_area,
            preserve_holes=request.preserve_holes,
        )
        round_trip = (
            _polygon_mask(
                polygons,
                width=request.raster.width,
                height=request.raster.height,
            )
            if polygons
            else np.zeros_like(cleaned)
        )
        if not polygons and bool(cleaned.any()):
            warnings.append("The cleaned raster could not be converted into polygon rings.")
        return RasterToPolygonResponse(
            polygons=polygons,
            cleaned_raster=encode_uncompressed_rle(
                cleaned,
                order=request.raster.order,
            ),
            quality=_quality(cleaned),
            round_trip_iou=mask_iou(cleaned, round_trip),
            preview_png_base64=_preview(cleaned),
            warnings=warnings,
        )

    def polygons_to_raster(
        self,
        request: PolygonToRasterRequest,
    ) -> PolygonToRasterResponse:
        mask = _polygon_mask(
            request.polygons,
            width=request.image_width,
            height=request.image_height,
        )
        return PolygonToRasterResponse(
            raster=encode_uncompressed_rle(mask, order=request.rle_order),
            quality=_quality(mask),
            preview_png_base64=_preview(mask),
            warnings=[],
        )

    def repair_polygons(self, request: PolygonRepairRequest) -> PolygonRepairResponse:
        original_intersections = sum(
            len(self_intersections(_ring(polygon.outer)))
            + sum(len(self_intersections(_ring(hole))) for hole in polygon.holes)
            for polygon in request.polygons
        )
        source = _polygon_mask(
            request.polygons,
            width=request.image_width,
            height=request.image_height,
        )
        polygons, cleaned, warnings = _vectorize(
            source,
            simplify_tolerance=request.simplify_tolerance,
            minimum_component_area=1,
            preserve_holes=request.preserve_holes,
        )
        repaired_intersections = sum(
            len(self_intersections(_ring(polygon.outer)))
            + sum(len(self_intersections(_ring(hole))) for hole in polygon.holes)
            for polygon in polygons
        )
        repaired_mask = (
            _polygon_mask(
                polygons,
                width=request.image_width,
                height=request.image_height,
            )
            if polygons
            else np.zeros_like(source)
        )
        if original_intersections:
            warnings.insert(
                0,
                "Self-intersections were repaired by rasterizing the submitted geometry and "
                "extracting valid component boundaries; inspect the editable preview.",
            )
        return PolygonRepairResponse(
            polygons=polygons,
            original_self_intersection_count=original_intersections,
            repaired_self_intersection_count=repaired_intersections,
            quality=_quality(cleaned),
            round_trip_iou=mask_iou(source, repaired_mask),
            preview_png_base64=_preview(cleaned),
            warnings=warnings,
        )
