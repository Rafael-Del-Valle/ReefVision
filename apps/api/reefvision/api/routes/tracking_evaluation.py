"""Tracker-independent reference evaluation endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.tracking_evaluation import (
    TrackingEvaluationRequest,
    TrackingEvaluationResponse,
    VideoTrackingEvaluationCreateRequest,
    VideoTrackingEvaluationRunResponse,
)
from reefvision.services.tracking_evaluation import (
    PersistedTrackingEvaluationService,
    TrackingEvaluationService,
)

router = APIRouter(tags=["tracking-evaluation"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post("/tracking/evaluate", response_model=TrackingEvaluationResponse)
def evaluate_tracking(payload: TrackingEvaluationRequest) -> TrackingEvaluationResponse:
    return TrackingEvaluationService().evaluate(payload)


@router.post(
    "/videos/{video_id}/tracking-evaluations",
    response_model=VideoTrackingEvaluationRunResponse,
    status_code=status.HTTP_201_CREATED,
)
def evaluate_persisted_video_tracking(
    video_id: str,
    payload: VideoTrackingEvaluationCreateRequest,
    session: DbSession,
) -> VideoTrackingEvaluationRunResponse:
    return PersistedTrackingEvaluationService(session).evaluate(video_id, payload)


@router.get(
    "/videos/{video_id}/tracking-evaluations",
    response_model=list[VideoTrackingEvaluationRunResponse],
)
def list_video_tracking_evaluations(
    video_id: str,
    session: DbSession,
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[VideoTrackingEvaluationRunResponse]:
    return PersistedTrackingEvaluationService(session).list(video_id, limit=limit)


@router.get(
    "/tracking-evaluations/{evaluation_id}",
    response_model=VideoTrackingEvaluationRunResponse,
)
def get_video_tracking_evaluation(
    evaluation_id: str,
    session: DbSession,
) -> VideoTrackingEvaluationRunResponse:
    return PersistedTrackingEvaluationService(session).get(evaluation_id)
