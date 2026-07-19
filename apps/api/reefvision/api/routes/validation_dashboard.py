"""Unified project validation dashboard endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.schemas.validation_dashboard import ValidationDashboardResponse
from reefvision.services.validation_dashboard import ValidationDashboardService

router = APIRouter(tags=["validation-dashboard"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.get(
    "/projects/{project_id}/validation-dashboard",
    response_model=ValidationDashboardResponse,
)
def get_validation_dashboard(
    project_id: str,
    request: Request,
    session: DbSession,
    verify_checksums: bool = Query(default=False),
    stale_job_minutes: int = Query(default=15, ge=1, le=10_080),
) -> ValidationDashboardResponse:
    settings: Settings = request.app.state.settings
    return ValidationDashboardService(session, settings).build(
        project_id,
        verify_checksums=verify_checksums,
        stale_job_minutes=stale_job_minutes,
    )
