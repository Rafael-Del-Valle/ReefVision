"""Raster/polygon conversion and editable repair-preview endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from reefvision.schemas.mask_conversion import (
    PolygonRepairRequest,
    PolygonRepairResponse,
    PolygonToRasterRequest,
    PolygonToRasterResponse,
    RasterToPolygonRequest,
    RasterToPolygonResponse,
)
from reefvision.services.mask_conversion import MaskConversionService

router = APIRouter(tags=["mask-conversion"])


@router.post(
    "/geometry/masks/raster-to-polygons",
    response_model=RasterToPolygonResponse,
)
def raster_to_polygons(payload: RasterToPolygonRequest) -> RasterToPolygonResponse:
    return MaskConversionService().raster_to_polygons(payload)


@router.post(
    "/geometry/masks/polygons-to-raster",
    response_model=PolygonToRasterResponse,
)
def polygons_to_raster(payload: PolygonToRasterRequest) -> PolygonToRasterResponse:
    return MaskConversionService().polygons_to_raster(payload)


@router.post(
    "/geometry/polygons/repair-rasterized",
    response_model=PolygonRepairResponse,
)
def repair_polygons(payload: PolygonRepairRequest) -> PolygonRepairResponse:
    return MaskConversionService().repair_polygons(payload)
