"""Complete-project archive, duplication, migration, and restoration endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.schemas.project_archives import (
    ProjectArchiveExportRequest,
    ProjectArchiveImportRequest,
    ProjectArchiveQueueResponse,
    ProjectArchiveVerificationResponse,
    ProjectDuplicateRequest,
    ProjectRestoreResponse,
    ProjectStorageMigrationRequest,
)
from reefvision.services.project_archives import ProjectArchiveService

router = APIRouter(tags=["project-archives"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> ProjectArchiveService:
    settings: Settings = request.app.state.settings
    return ProjectArchiveService(session, settings)


@router.post(
    "/projects/{project_id}/archive-export",
    response_model=ProjectArchiveQueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def queue_project_archive_export(
    project_id: str,
    payload: ProjectArchiveExportRequest,
    request: Request,
    session: DbSession,
) -> ProjectArchiveQueueResponse:
    return service(request, session).queue_export(project_id, payload)


@router.get(
    "/project-archives/verify",
    response_model=ProjectArchiveVerificationResponse,
)
def verify_project_archive(
    request: Request,
    session: DbSession,
    archive_path: Annotated[str, Query(min_length=1, max_length=4000)],
) -> ProjectArchiveVerificationResponse:
    return service(request, session).verify(archive_path)


@router.post(
    "/project-archives/import",
    response_model=ProjectArchiveQueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def queue_project_archive_import(
    payload: ProjectArchiveImportRequest,
    request: Request,
    session: DbSession,
) -> ProjectArchiveQueueResponse:
    return service(request, session).queue_import(payload)


@router.post(
    "/projects/{project_id}/duplicate",
    response_model=ProjectArchiveQueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def queue_project_duplicate(
    project_id: str,
    payload: ProjectDuplicateRequest,
    request: Request,
    session: DbSession,
) -> ProjectArchiveQueueResponse:
    return service(request, session).queue_duplicate(project_id, payload)


@router.post(
    "/projects/{project_id}/storage-migration",
    response_model=ProjectArchiveQueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def queue_project_storage_migration(
    project_id: str,
    payload: ProjectStorageMigrationRequest,
    request: Request,
    session: DbSession,
) -> ProjectArchiveQueueResponse:
    return service(request, session).queue_storage_migration(project_id, payload)


@router.post(
    "/projects/{project_id}/restore",
    response_model=ProjectRestoreResponse,
)
def restore_archived_project(
    project_id: str,
    request: Request,
    session: DbSession,
) -> ProjectRestoreResponse:
    return service(request, session).restore(project_id)
