"""Persisted Milestone 8 backup-history records."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class BackupRecord(Base):
    """An application-wide managed backup and its lifecycle metadata."""

    __tablename__ = "backup_records"
    __table_args__ = (Index("ix_backup_records_status_created", "status", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    job_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued", index=True)
    format_version: Mapped[str] = mapped_column(String(20), nullable=False)
    destination_path: Mapped[str] = mapped_column(String(700), nullable=False, unique=True)
    staging_path: Mapped[str | None] = mapped_column(String(700), nullable=True)
    manifest_path: Mapped[str] = mapped_column(String(700), nullable=False)
    completion_marker_path: Mapped[str] = mapped_column(String(700), nullable=False)
    database_filename: Mapped[str] = mapped_column(String(120), nullable=False)
    request_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
