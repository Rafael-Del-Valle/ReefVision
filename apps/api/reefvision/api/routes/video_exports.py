"""Rendered annotated, trajectory, and heatmap video export endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.video_exports import (
    VideoDataExportRequest,
    VideoDataExportResponse,
    VideoRenderExportRequest,
    VideoRenderExportResponse,
)
from reefvision.services.video_data_exports import VideoDataExportService
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


@router.post(
    "/videos/{video_id}/data-exports",
    response_model=VideoDataExportResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_video_data_export(
    video_id: str,
    payload: VideoDataExportRequest,
    request: Request,
    session: DbSession,
) -> VideoDataExportResponse:
    return VideoDataExportService(
        session,
        request.app.state.settings,
    ).export(video_id, payload)
