"""Backup-record persistence operations."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import BackupRecord


class BackupRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, backup: BackupRecord) -> None:
        self.session.add(backup)

    def get(self, backup_id: str) -> BackupRecord | None:
        return self.session.get(BackupRecord, backup_id)

    def get_by_job_id(self, job_id: str) -> BackupRecord | None:
        statement = select(BackupRecord).where(BackupRecord.job_id == job_id)
        return self.session.scalar(statement)

    def list_all(self) -> list[BackupRecord]:
        statement = select(BackupRecord).order_by(BackupRecord.created_at.desc(), BackupRecord.id)
        return list(self.session.scalars(statement))
