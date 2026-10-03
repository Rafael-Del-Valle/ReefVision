"""Scientist-ready behavior ethogram and dynamics routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.behavior_dynamics import (
    BehaviorBoutCreateRequest,
    BehaviorBoutResponse,
    BehaviorDynamicsRequest,
    BehaviorDynamicsResponse,
    BehaviorEthogramCreateRequest,
    BehaviorEthogramResponse,
)
from reefvision.services.behavior_dynamics import BehaviorDynamicsService

router = APIRouter(tags=["behavior-dynamics"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post(
    "/projects/{project_id}/behavior-ethograms",
    response_model=BehaviorEthogramResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_behavior_ethogram(
    project_id: str,
    payload: BehaviorEthogramCreateRequest,
    session: DbSession,
) -> BehaviorEthogramResponse:
    return BehaviorDynamicsService(session).create_ethogram(project_id, payload)


@router.get(
    "/projects/{project_id}/behavior-ethograms",
    response_model=list[BehaviorEthogramResponse],
)
def list_behavior_ethograms(
    project_id: str,
    session: DbSession,
) -> list[BehaviorEthogramResponse]:
    return BehaviorDynamicsService(session).list_ethograms(project_id)


@router.post(
    "/video-tracks/{track_id}/behavior-bouts",
    response_model=BehaviorBoutResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_behavior_bout(
    track_id: str,
    payload: BehaviorBoutCreateRequest,
    session: DbSession,
) -> BehaviorBoutResponse:
    return BehaviorDynamicsService(session).create_bout(track_id, payload)


@router.get(
    "/video-tracks/{track_id}/behavior-bouts",
    response_model=list[BehaviorBoutResponse],
)
def list_behavior_bouts(
    track_id: str,
    session: DbSession,
    ethogram_revision_id: Annotated[str | None, Query(max_length=36)] = None,
) -> list[BehaviorBoutResponse]:
    return BehaviorDynamicsService(session).list_bouts(
        track_id,
        ethogram_revision_id,
    )


@router.post(
    "/video-tracks/{track_id}/behavior-dynamics",
    response_model=BehaviorDynamicsResponse,
)
def behavior_dynamics(
    track_id: str,
    payload: BehaviorDynamicsRequest,
    session: DbSession,
) -> BehaviorDynamicsResponse:
    return BehaviorDynamicsService(session).analyze(track_id, payload)
