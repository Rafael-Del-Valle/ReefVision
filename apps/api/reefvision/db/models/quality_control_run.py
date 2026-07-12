"""Persisted quality-control run metadata and history."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now

if TYPE_CHECKING:
    from reefvision.db.models.dataset_version import DatasetVersion
    from reefvision.db.models.job import Job
    from reefvision.db.models.project import Project
    from reefvision.db.models.quality_control_issue import QualityControlIssue


class QualityControlRun(Base):
    """A historical, deterministic quality-control evaluation run."""

    __tablename__ = "quality_control_runs"
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_quality_control_runs_job_id"),
        Index("ix_quality_control_runs_project_status", "project_id", "status"),
        Index("ix_quality_control_runs_dataset_status", "dataset_version_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dataset_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("dataset_versions.id", ondelete="SET NULL"), nullable=True
    )
    job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    scope_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    rule_categories_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    selected_rule_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    thresholds_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    configuration_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    input_checksums_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    issue_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False, default="local_user")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped[Project] = relationship()
    dataset_version: Mapped[DatasetVersion | None] = relationship()
    job: Mapped[Job | None] = relationship()
    issues: Mapped[list[QualityControlIssue]] = relationship(
        back_populates="quality_control_run",
        cascade="all, delete-orphan",
        order_by="QualityControlIssue.created_at",
    )
