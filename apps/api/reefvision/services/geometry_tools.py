"""Stateless polygon editing, repair, conversion, and Boolean operations."""

from __future__ import annotations

from reefvision.ml.mask_tools import (
    boolean_masks,
    convex_hull,
    densify_ring,
    mask_to_rings,
    normalize_ring,
    polygon_quality,
    polygon_to_mask,
    raster_quality,
    simplify_ring,
    snap_ring,
)
from reefvision.schemas.geometry_tools import (
    GeometryPoint,
    PolygonAnalyzeRequest,
    PolygonAnalyzeResponse,
    PolygonBooleanRequest,
    PolygonBooleanResponse,
    PolygonGeometry,
    PolygonTransformRequest,
    PolygonTransformResponse,
)


def _ring(points: list[GeometryPoint]) -> list[tuple[float, float]]:
    return [(float(point.x), float(point.y)) for point in points]


def _schema_ring(points: list[tuple[float, float]]) -> list[GeometryPoint]:
    return [GeometryPoint(x=x, y=y) for x, y in points]


def _geometry(
    outer: list[tuple[float, float]],
    holes: list[list[tuple[float, float]]],
) -> PolygonGeometry:
    return PolygonGeometry(
        outer=_schema_ring(outer),
        holes=[_schema_ring(hole) for hole in holes],
    )


def _analysis(
    polygon: PolygonGeometry,
    *,
    width: int,
    height: int,
) -> PolygonAnalyzeResponse:
    quality = polygon_quality(_ring(polygon.outer), width=width, height=height)
    return PolygonAnalyzeResponse(
        area=quality.area,
        perimeter=quality.perimeter,
        orientation=quality.orientation,
        self_intersections=list(quality.self_intersections),
        outside_vertex_count=quality.outside_vertex_count,
        touches_boundary=quality.touches_boundary,
        vertex_count=quality.vertex_count,
        hole_count=len(polygon.holes),
    )


class GeometryToolsService:
    def analyze(self, request: PolygonAnalyzeRequest) -> PolygonAnalyzeResponse:
        return _analysis(
            request.polygon,
            width=request.image_width,
            height=request.image_height,
        )

    def transform(self, request: PolygonTransformRequest) -> PolygonTransformResponse:
        outer = _ring(request.polygon.outer)
        holes = [_ring(hole) for hole in request.polygon.holes]
        warnings: list[str] = []
        if request.operation == "simplify":
            outer = simplify_ring(outer, tolerance=float(request.tolerance))
            holes = [
                simplify_ring(hole, tolerance=float(request.tolerance)) for hole in holes
            ]
        elif request.operation == "densify":
            outer = densify_ring(
                outer,
                maximum_segment_length=float(request.maximum_segment_length),
            )
            holes = [
                densify_ring(
                    hole,
                    maximum_segment_length=float(request.maximum_segment_length),
                )
                for hole in holes
            ]
        elif request.operation == "repair_convex_hull":
            outer = convex_hull(outer)
            holes = []
            warnings.append(
                "Convex-hull repair removes concavities and polygon holes; inspect the result."
            )
        elif request.operation == "normalize_clockwise":
            outer = normalize_ring(outer, clockwise=True)
            holes = [normalize_ring(hole, clockwise=False) for hole in holes]
        elif request.operation == "normalize_counterclockwise":
            outer = normalize_ring(outer, clockwise=False)
            holes = [normalize_ring(hole, clockwise=True) for hole in holes]
        elif request.operation == "snap_to_edges":
            outer = snap_ring(
                outer,
                width=request.image_width,
                height=request.image_height,
                edge_distance=float(request.edge_distance),
            )
            holes = [
                snap_ring(
                    hole,
                    width=request.image_width,
                    height=request.image_height,
                    edge_distance=float(request.edge_distance),
                )
                for hole in holes
            ]
        polygon = _geometry(outer, holes)
        return PolygonTransformResponse(
            polygon=polygon,
            analysis=_analysis(
                polygon,
                width=request.image_width,
                height=request.image_height,
            ),
            warnings=warnings,
        )

    def boolean(self, request: PolygonBooleanRequest) -> PolygonBooleanResponse:
        first = polygon_to_mask(
            _ring(request.first.outer),
            width=request.image_width,
            height=request.image_height,
            holes=[_ring(hole) for hole in request.first.holes],
        )
        second = polygon_to_mask(
            _ring(request.second.outer),
            width=request.image_width,
            height=request.image_height,
            holes=[_ring(hole) for hole in request.second.holes],
        )
        result = boolean_masks(first, second, operation=request.operation)
        quality = raster_quality(result)
        rings = mask_to_rings(result)
        warnings: list[str] = []
        if not rings:
            warnings.append("The Boolean operation produced an empty result.")
        return PolygonBooleanResponse(
            rings=[_schema_ring(ring) for ring in rings],
            foreground_pixels=quality.area_pixels,
            component_count=quality.component_count,
            hole_count=quality.hole_count,
            warnings=warnings,
        )
