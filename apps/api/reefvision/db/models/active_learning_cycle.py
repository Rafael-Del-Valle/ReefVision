"""Persisted active-learning selection, review, training, and promotion cycles."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class ActiveLearningCycle(Base):
    __tablename__ = "active_learning_cycles"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "cycle_index",
            name="uq_active_learning_cycles_project_index",
        ),
        Index("ix_active_learning_cycles_project_status", "project_id", "status"),
        Index("ix_active_learning_cycles_parent", "parent_cycle_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_cycle_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("active_learning_cycles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    cycle_index: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="selection")
    selection_strategy: Mapped[str] = mapped_column(String(80), nullable=False)
    annotation_budget: Mapped[int] = mapped_column(Integer, nullable=False)
    selected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reviewed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_model_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("model_registrations.id", ondelete="SET NULL"),
        nullable=True,
    )
    candidate_model_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("model_registrations.id", ondelete="SET NULL"),
        nullable=True,
    )
    promoted_model_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("model_registrations.id", ondelete="SET NULL"),
        nullable=True,
    )
    dataset_version_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("dataset_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    training_run_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("training_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    review_queue_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("review_queues.id", ondelete="SET NULL"),
        nullable=True,
    )
    selection_config_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    selection_result_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    baseline_metrics_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    candidate_metrics_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    promotion_gates_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    promotion_result_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    stop_conditions_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    history_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
