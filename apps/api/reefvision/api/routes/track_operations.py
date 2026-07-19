"""Revision-safe video-track correction endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.track_operations import (
    TrackIdentitySwapRequest,
    TrackMergeRequest,
    TrackOperationResponse,
    TrackSplitRequest,
)
from reefvision.services.track_operations import TrackOperationService

router = APIRouter(tags=["track-operations"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post("/video-tracks/{track_id}/split", response_model=TrackOperationResponse)
def split_track(
    track_id: str,
    payload: TrackSplitRequest,
    session: DbSession,
) -> TrackOperationResponse:
    return TrackOperationService(session).split(track_id, payload)


@router.post("/videos/{video_id}/tracks/merge", response_model=TrackOperationResponse)
def merge_tracks(
    video_id: str,
    payload: TrackMergeRequest,
    session: DbSession,
) -> TrackOperationResponse:
    return TrackOperationService(session).merge(video_id, payload)


@router.post(
    "/videos/{video_id}/tracks/swap-identities",
    response_model=TrackOperationResponse,
)
def swap_track_identities(
    video_id: str,
    payload: TrackIdentitySwapRequest,
    session: DbSession,
) -> TrackOperationResponse:
    return TrackOperationService(session).swap_identities(video_id, payload)
