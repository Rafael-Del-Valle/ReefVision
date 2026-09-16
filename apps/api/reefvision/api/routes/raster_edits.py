"""Raster mask brush and eraser endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.schemas.polygon_fill import (
    PolygonFillRequest,
    PolygonFillResponse,
    SmartCloseRequest,
)
from reefvision.schemas.raster_edits import (
    RasterMaskClassUpdateRequest,
    RasterMaskEditRequest,
    RasterMaskEditResponse,
)
from reefvision.services.polygon_fill import (
    generate_polygon_fill,
    generate_smart_close_polygon,
)
from reefvision.services.raster_edits import RasterMaskEditService

router = APIRouter(tags=["raster_edits"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post("/images/{image_id}/polygon-fill", response_model=PolygonFillResponse)
def polygon_fill(
    image_id: str, payload: PolygonFillRequest, request: Request, session: DbSession
) -> PolygonFillResponse:
    return generate_polygon_fill(session, request.app.state.settings, image_id, payload)


@router.post(
    "/images/{image_id}/smart-close-polygon",
    response_model=PolygonFillResponse,
)
def smart_close_polygon(
    image_id: str, payload: SmartCloseRequest, request: Request, session: DbSession
) -> PolygonFillResponse:
    return generate_smart_close_polygon(
        session,
        request.app.state.settings,
        image_id,
        payload,
    )


@router.post(
    "/images/{image_id}/raster-mask-edits",
    response_model=RasterMaskEditResponse,
)
def edit_raster_mask(
    image_id: str,
    payload: RasterMaskEditRequest,
    request: Request,
    session: DbSession,
) -> RasterMaskEditResponse:
    settings: Settings = request.app.state.settings
    return RasterMaskEditService(session, settings).edit(image_id, payload)


@router.patch(
    "/images/{image_id}/raster-mask-annotations/{mask_annotation_id}/class",
    response_model=RasterMaskEditResponse,
)
def reclassify_raster_mask(
    image_id: str,
    mask_annotation_id: str,
    payload: RasterMaskClassUpdateRequest,
    request: Request,
    session: DbSession,
) -> RasterMaskEditResponse:
    settings: Settings = request.app.state.settings
    return RasterMaskEditService(session, settings).reclassify(
        image_id,
        mask_annotation_id,
        payload,
    )
