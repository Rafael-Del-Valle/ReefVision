"""Project-managed storage and record-integrity endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.project_integrity import ProjectIntegrityResponse
from reefvision.services.project_integrity import ProjectIntegrityService

router = APIRouter(tags=["project-integrity"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.get(
    "/projects/{project_id}/integrity",
    response_model=ProjectIntegrityResponse,
)
def inspect_project_integrity(
    project_id: str,
    request: Request,
    session: DbSession,
    verify_checksums: Annotated[bool, Query()] = False,
    stale_job_minutes: Annotated[int, Query(ge=1, le=43_200)] = 60,
) -> ProjectIntegrityResponse:
    return ProjectIntegrityService(
        session,
        request.app.state.settings,
    ).inspect(
        project_id,
        verify_checksums=verify_checksums,
        stale_job_minutes=stale_job_minutes,
    )
