"""Rendered annotated, trajectory, and heatmap video export endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.video_exports import (
    VideoRenderExportRequest,
    VideoRenderExportResponse,
)
from reefvision.services.video_exports import VideoRenderExportService

router = APIRouter(tags=["video-exports"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post(
    "/videos/{video_id}/render-exports",
    response_model=VideoRenderExportResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def queue_video_render_export(
    video_id: str,
    payload: VideoRenderExportRequest,
    session: DbSession,
) -> VideoRenderExportResponse:
    return VideoRenderExportService(session).queue(video_id, payload)
