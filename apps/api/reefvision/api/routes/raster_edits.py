"""Raster mask brush and eraser endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.schemas.raster_edits import RasterMaskEditRequest, RasterMaskEditResponse
from reefvision.services.raster_edits import RasterMaskEditService

router = APIRouter(tags=["raster_edits"])
DbSession = Annotated[Session, Depends(get_db_session)]


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
