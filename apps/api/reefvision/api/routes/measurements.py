"""Scientific mask measurement endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.schemas.measurements import MaskMeasurementResponse
from reefvision.services.mask_measurements import MaskMeasurementService

router = APIRouter(tags=["measurements"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.get(
    "/mask-annotations/{mask_annotation_id}/measurements",
    response_model=MaskMeasurementResponse,
)
def get_mask_measurements(
    mask_annotation_id: str,
    request: Request,
    session: DbSession,
) -> MaskMeasurementResponse:
    settings: Settings = request.app.state.settings
    return MaskMeasurementService(session, settings).measure(mask_annotation_id)
