"""Persisted background-job database model."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class Job(Base):
    """A resumable local background operation."""

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status_created", "status", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    job_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    deduplication_key: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="queued", index=True)
    progress_current: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    request_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LocalComputeLimits(Base):
    """Machine-local queue settings shared by every project in the profile."""

    __tablename__ = "local_compute_limits"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_local_compute_singleton"),
        CheckConstraint("cpu_slots BETWEEN 0 AND 8", name="ck_local_compute_cpu"),
        CheckConstraint("gpu_slots BETWEEN 0 AND 1", name="ck_local_compute_gpu"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cpu_slots: Mapped[int] = mapped_column(Integer, nullable=False)
    gpu_slots: Mapped[int] = mapped_column(Integer, nullable=False)


class LocalComputeLease(Base):
    """A token protects this job's slot until its dispatcher returns."""

    __tablename__ = "local_compute_leases"

    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True)
    token: Mapped[str] = mapped_column(String(36), nullable=False)
    pool: Mapped[str] = mapped_column(String(6), nullable=False)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
