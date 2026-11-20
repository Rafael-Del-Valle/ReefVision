"""Local recurring workflows and the durable identity of each due occurrence."""

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class WorkflowSchedule(Base):
    __tablename__ = "workflow_schedules"
    __table_args__ = (
        Index("ix_workflow_schedules_due", "enabled", "next_due_at"),
        Index("ix_workflow_schedules_project", "project_id", "created_at", "id"),
        CheckConstraint("interval_seconds > 0", name="ck_workflow_schedule_interval"),
        CheckConstraint("minimum_free_bytes >= 0", name="ck_workflow_schedule_storage"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(200))
    purpose: Mapped[str] = mapped_column(String(20))
    workflow_graph_record_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_graph_records.id", ondelete="RESTRICT")
    )
    graph_sha256: Mapped[str] = mapped_column(String(64))
    inputs_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    inputs_sha256: Mapped[str] = mapped_column(String(64))
    interval_seconds: Mapped[int] = mapped_column(Integer)
    next_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    minimum_free_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    last_status: Mapped[str] = mapped_column(String(32), default="scheduled")
    last_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class WorkflowScheduleOccurrence(Base):
    __tablename__ = "workflow_schedule_occurrences"
    __table_args__ = (
        UniqueConstraint("schedule_id", "scheduled_at", name="uq_workflow_occurrence_slot"),
        UniqueConstraint("workflow_run_id", name="uq_workflow_occurrence_run"),
        Index("ix_workflow_occurrences_project", "project_id", "created_at"),
        CheckConstraint("missed_intervals >= 0", name="ck_workflow_occurrence_missed"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE")
    )
    schedule_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_schedules.id", ondelete="CASCADE")
    )
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    missed_intervals: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str | None] = mapped_column(Text)
    workflow_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("workflow_runs.id", ondelete="RESTRICT")
    )
    graph_sha256: Mapped[str] = mapped_column(String(64))
    inputs_sha256: Mapped[str] = mapped_column(String(64))
