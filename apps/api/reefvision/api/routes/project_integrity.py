"""Project-managed storage, integrity, and safe-repair endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.project_integrity import (
    ProjectIntegrityResponse,
    ProjectRepairApplyRequest,
    ProjectRepairApplyResponse,
    ProjectRepairPlanResponse,
)
from reefvision.services.project_integrity_runtime import ProjectIntegrityRuntimeService
from reefvision.services.project_repairs import ProjectRepairService

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
    return ProjectIntegrityRuntimeService(
        session,
        request.app.state.settings,
    ).inspect(
        project_id,
        verify_checksums=verify_checksums,
        stale_job_minutes=stale_job_minutes,
    )


@router.get(
    "/projects/{project_id}/integrity/repair-plan",
    response_model=ProjectRepairPlanResponse,
)
def preview_project_repairs(
    project_id: str,
    request: Request,
    session: DbSession,
    minimum_orphan_age_seconds: Annotated[
        int,
        Query(ge=60, le=31_536_000),
    ] = 3600,
) -> ProjectRepairPlanResponse:
    return ProjectRepairService(
        session,
        request.app.state.settings,
    ).plan(
        project_id,
        minimum_orphan_age_seconds=minimum_orphan_age_seconds,
    )


@router.post(
    "/projects/{project_id}/integrity/repairs",
    response_model=ProjectRepairApplyResponse,
)
def apply_project_repairs(
    project_id: str,
    payload: ProjectRepairApplyRequest,
    request: Request,
    session: DbSession,
) -> ProjectRepairApplyResponse:
    return ProjectRepairService(
        session,
        request.app.state.settings,
    ).apply(
        project_id,
        payload.action_ids,
        minimum_orphan_age_seconds=payload.minimum_orphan_age_seconds,
    )
