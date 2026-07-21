"""Persisted review-queue items and state transitions."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now

if TYPE_CHECKING:
    from reefvision.db.models.project import Project
    from reefvision.db.models.review_queue import ReviewQueue


class ReviewQueueItem(Base):
    """A ranked image recommendation in a generated review queue."""

    __tablename__ = "review_queue_items"
    __table_args__ = (
        Index("ix_review_queue_items_queue_state", "review_queue_id", "review_state"),
        Index("ix_review_queue_items_queue_score", "review_queue_id", "score"),
        Index("ix_review_queue_items_project_image", "project_id", "image_id"),
        Index("ix_review_queue_items_queue_severity", "review_queue_id", "highest_qc_severity"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    review_queue_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("review_queues.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dataset_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    image_id: Mapped[str] = mapped_column(String(36), nullable=False)
    split: Mapped[str | None] = mapped_column(String(20), nullable=True)
    review_state: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    score: Mapped[float] = mapped_column(Float, nullable=False)
    rank_position: Mapped[int] = mapped_column(Integer, nullable=False)
    highest_qc_severity: Mapped[str | None] = mapped_column(String(20), nullable=True)
    label_class_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    model_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    related_issue_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    signal_values_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    normalized_signals_json: Mapped[dict[str, float]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    weights_json: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False, default=dict)
    score_breakdown_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    input_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    selection_reasons_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    manual_state: Mapped[str] = mapped_column(String(30), nullable=False, default="automatic")
    fragment_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    near_duplicate_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    skip_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    review_queue: Mapped[ReviewQueue] = relationship(back_populates="items")
    project: Mapped[Project] = relationship()
