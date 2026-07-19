"""SAM 2 video-mask propagation endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.sam2_video import (
    SAM2VideoPropagationRequest,
    SAM2VideoPropagationResponse,
)
from reefvision.services.sam2_video import SAM2VideoPropagationService

router = APIRouter(tags=["sam2-video"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post(
    "/videos/{video_id}/sam2-propagation",
    response_model=SAM2VideoPropagationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def queue_sam2_video_propagation(
    video_id: str,
    payload: SAM2VideoPropagationRequest,
    session: DbSession,
) -> SAM2VideoPropagationResponse:
    return SAM2VideoPropagationService(session).queue(video_id, payload)
