"""Auditable class-reassignment and deletion operations."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class ClassOperation(Base):
    """A persisted preview or execution record for a class operation."""

    __tablename__ = "class_operations"
    __table_args__ = (
        Index("ix_class_operations_project_created", "project_id", "created_at"),
        Index("ix_class_operations_project_status", "project_id", "status"),
        Index("ix_class_operations_source_target", "source_class_id", "target_class_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_class_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    target_class_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    operation_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="previewed")
    preview_checksum: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    requested_by_identity: Mapped[str] = mapped_column(String(200), nullable=False)
    source_class_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    target_class_snapshot_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    plan_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    affected_counts_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    protected_reference_counts_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    warnings_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    failures_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    rollback_result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    final_state: Mapped[str | None] = mapped_column(String(60), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
