"""Milestone 8 managed backup endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.schemas.backups import (
    BackupCreateRequest,
    BackupCreateResponse,
    BackupRecordResponse,
    BackupRestoreRequest,
    BackupRestoreResponse,
    BackupVerificationResponse,
)
from reefvision.services.backups import BackupService

router = APIRouter(tags=["backups"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> BackupService:
    settings: Settings = request.app.state.settings
    return BackupService(session, settings)


@router.get("/backups", response_model=list[BackupRecordResponse])
def list_backups(request: Request, session: DbSession) -> list[BackupRecordResponse]:
    return service(request, session).list_backups()


@router.post("/backups", response_model=BackupCreateResponse, status_code=status.HTTP_201_CREATED)
def create_backup(
    payload: BackupCreateRequest,
    request: Request,
    session: DbSession,
) -> BackupCreateResponse:
    return service(request, session).create_backup(payload)


@router.get("/backups/{backup_id}", response_model=BackupRecordResponse)
def get_backup(backup_id: str, request: Request, session: DbSession) -> BackupRecordResponse:
    return service(request, session).get_backup(backup_id)


@router.post("/backups/{backup_id}/verify", response_model=BackupVerificationResponse)
def verify_backup(
    backup_id: str,
    request: Request,
    session: DbSession,
) -> BackupVerificationResponse:
    return service(request, session).verify_backup(backup_id)


@router.post("/backups/{backup_id}/restore", response_model=BackupRestoreResponse)
def restore_backup(
    backup_id: str,
    payload: BackupRestoreRequest,
    request: Request,
    session: DbSession,
) -> BackupRestoreResponse:
    return service(request, session).restore_backup(backup_id, payload)
