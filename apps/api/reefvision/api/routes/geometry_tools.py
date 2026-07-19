"""Polygon analysis, repair, and Boolean-operation endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from reefvision.schemas.geometry_tools import (
    PolygonAnalyzeRequest,
    PolygonAnalyzeResponse,
    PolygonBooleanRequest,
    PolygonBooleanResponse,
    PolygonTransformRequest,
    PolygonTransformResponse,
)
from reefvision.services.geometry_tools import GeometryToolsService

router = APIRouter(tags=["geometry-tools"])


@router.post("/geometry/polygons/analyze", response_model=PolygonAnalyzeResponse)
def analyze_polygon(payload: PolygonAnalyzeRequest) -> PolygonAnalyzeResponse:
    return GeometryToolsService().analyze(payload)


@router.post("/geometry/polygons/transform", response_model=PolygonTransformResponse)
def transform_polygon(payload: PolygonTransformRequest) -> PolygonTransformResponse:
    return GeometryToolsService().transform(payload)


@router.post("/geometry/polygons/boolean", response_model=PolygonBooleanResponse)
def boolean_polygons(payload: PolygonBooleanRequest) -> PolygonBooleanResponse:
    return GeometryToolsService().boolean(payload)
