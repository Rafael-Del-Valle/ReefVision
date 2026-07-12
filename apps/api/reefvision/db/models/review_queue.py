"""Persisted historical review-queue generation records."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now

if TYPE_CHECKING:
    from reefvision.db.models.dataset_version import DatasetVersion
    from reefvision.db.models.project import Project
    from reefvision.db.models.review_queue_item import ReviewQueueItem


class ReviewQueue(Base):
    """A historical review-queue snapshot and its generation config."""

    __tablename__ = "review_queues"
    __table_args__ = (
        Index("ix_review_queues_project_created", "project_id", "created_at"),
        Index("ix_review_queues_dataset_created", "dataset_version_id", "created_at"),
        Index("ix_review_queues_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dataset_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("dataset_versions.id", ondelete="SET NULL"), nullable=True
    )
    source_quality_control_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("quality_control_runs.id", ondelete="SET NULL"), nullable=True
    )
    regenerated_from_queue_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("review_queues.id", ondelete="SET NULL"), nullable=True
    )
    scope_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="complete")
    formula_id: Mapped[str] = mapped_column(String(100), nullable=False)
    formula_version: Mapped[str] = mapped_column(String(40), nullable=False)
    configuration_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    input_checksums_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False, default="local_user")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped[Project] = relationship()
    dataset_version: Mapped[DatasetVersion | None] = relationship()
    items: Mapped[list[ReviewQueueItem]] = relationship(
        back_populates="review_queue",
        cascade="all, delete-orphan",
        order_by="ReviewQueueItem.rank_position",
    )
