"""Persisted active-learning acquisition rounds."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class ActiveLearningRound(Base):
    __tablename__ = "active_learning_rounds"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "selection_sha256", name="uq_active_learning_round_selection"
        ),
        Index("ix_active_learning_rounds_project_created", "project_id", "created_at"),
        Index("ix_active_learning_rounds_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    dataset_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("dataset_versions.id", ondelete="SET NULL"), nullable=True
    )
    review_queue_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("review_queues.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    strategy: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="open")
    requested_size: Mapped[int] = mapped_column(Integer, nullable=False)
    selected_count: Mapped[int] = mapped_column(Integer, nullable=False)
    model_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    strategy_config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    selection_manifest_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    selection_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    feedback_summary_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    created_by: Mapped[str] = mapped_column(String(100), nullable=False, default="local_user")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
