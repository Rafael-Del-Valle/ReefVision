"""Polygon analysis, repair, conversion, and Boolean-operation schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, FiniteFloat, model_validator


class GeometryPoint(BaseModel):
    x: FiniteFloat
    y: FiniteFloat


class PolygonGeometry(BaseModel):
    outer: list[GeometryPoint] = Field(min_length=3, max_length=1_000_000)
    holes: list[list[GeometryPoint]] = Field(default_factory=list, max_length=10_000)

    @model_validator(mode="after")
    def validate_holes(self) -> PolygonGeometry:
        if any(len(hole) < 3 for hole in self.holes):
            raise ValueError("Polygon holes require at least three points")
        return self


class PolygonAnalyzeRequest(BaseModel):
    polygon: PolygonGeometry
    image_width: int = Field(ge=1, le=1_000_000)
    image_height: int = Field(ge=1, le=1_000_000)


class PolygonAnalyzeResponse(BaseModel):
    area: float
    perimeter: float
    orientation: str
    self_intersections: list[tuple[int, int]]
    outside_vertex_count: int
    touches_boundary: bool
    vertex_count: int
    hole_count: int


class PolygonTransformRequest(PolygonAnalyzeRequest):
    operation: Literal[
        "simplify",
        "densify",
        "repair_convex_hull",
        "normalize_clockwise",
        "normalize_counterclockwise",
        "snap_to_edges",
    ]
    tolerance: FiniteFloat = Field(default=1, ge=0, le=100_000)
    maximum_segment_length: FiniteFloat = Field(default=10, gt=0, le=100_000)
    edge_distance: FiniteFloat = Field(default=4, ge=0, le=100_000)


class PolygonTransformResponse(BaseModel):
    polygon: PolygonGeometry
    analysis: PolygonAnalyzeResponse
    warnings: list[str]


class PolygonBooleanRequest(BaseModel):
    first: PolygonGeometry
    second: PolygonGeometry
    operation: Literal["union", "intersection", "subtract", "xor"]
    image_width: int = Field(ge=1, le=100_000)
    image_height: int = Field(ge=1, le=100_000)


class PolygonBooleanResponse(BaseModel):
    rings: list[list[GeometryPoint]]
    foreground_pixels: int
    component_count: int
    hole_count: int
    warnings: list[str]
