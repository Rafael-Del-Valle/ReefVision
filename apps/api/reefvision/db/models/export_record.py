"""Export record for immutable dataset-version artifacts."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now

if TYPE_CHECKING:
    from reefvision.db.models.dataset_version import DatasetVersion
    from reefvision.db.models.job import Job
    from reefvision.db.models.project import Project


class ExportRecord(Base):
    """A persisted export request and its generated artifact paths."""

    __tablename__ = "exports"
    __table_args__ = (
        Index("ix_exports_project_status", "project_id", "status"),
        Index("ix_exports_version_status", "dataset_version_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dataset_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("dataset_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    format: Mapped[str] = mapped_column(String(60), nullable=False)
    output_path: Mapped[str] = mapped_column(String(700), nullable=False)
    manifest_path: Mapped[str] = mapped_column(String(700), nullable=False)
    archive_path: Mapped[str] = mapped_column(String(700), nullable=False)
    request_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[Project] = relationship(back_populates="exports")
    dataset_version: Mapped[DatasetVersion] = relationship(back_populates="exports")
    job: Mapped[Job | None] = relationship()
