"""Persisted ReefVision project exchange packages."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class ProjectExchangePackage(Base):
    __tablename__ = "project_exchange_packages"
    __table_args__ = (
        Index("ix_project_exchange_packages_project_created", "project_id", "created_at"),
        Index("ix_project_exchange_packages_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    direction: Mapped[str] = mapped_column(String(20), nullable=False, default="export")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    format_version: Mapped[str] = mapped_column(String(20), nullable=False)
    manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    archive_path: Mapped[str] = mapped_column(String(700), nullable=False)
    options_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
