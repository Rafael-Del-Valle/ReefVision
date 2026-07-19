"""Project restart inspection endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.schemas.recovery import (
    RecoveryApplyRequest,
    RecoveryApplyResponse,
    RecoveryPlanResponse,
)
from reefvision.services.recovery import RecoveryService

router = APIRouter(tags=["project-recovery"])
DbSession = Annotated[Session, Depends(get_db_session)]


def _service(request: Request, session: Session) -> RecoveryService:
    settings: Settings = request.app.state.settings
    return RecoveryService(session, settings)


@router.get("/projects/{project_id}/recovery-plan", response_model=RecoveryPlanResponse)
def get_recovery_plan(
    project_id: str,
    request: Request,
    session: DbSession,
    stale_after_seconds: int = Query(default=300, ge=30, le=86_400),
) -> RecoveryPlanResponse:
    return _service(request, session).plan(
        project_id,
        stale_after_seconds=stale_after_seconds,
    )


@router.post(
    "/projects/{project_id}/recovery-plan/actions",
    response_model=RecoveryApplyResponse,
)
def run_recovery_actions(
    project_id: str,
    payload: RecoveryApplyRequest,
    request: Request,
    session: DbSession,
    stale_after_seconds: int = Query(default=300, ge=30, le=86_400),
) -> RecoveryApplyResponse:
    return _service(request, session).apply(
        project_id,
        payload.issue_ids,
        stale_after_seconds=stale_after_seconds,
    )
