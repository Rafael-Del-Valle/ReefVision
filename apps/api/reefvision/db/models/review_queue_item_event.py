"""Append-only local QC review comments and assignment events."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class ReviewQueueItemEvent(Base):
    """Manual coordination only; not evidence of verified annotations."""

    __tablename__ = "review_queue_item_events"
    __table_args__ = (
        UniqueConstraint(
            "review_queue_item_id",
            "client_request_id",
            name="uq_review_queue_item_event_request",
        ),
        Index(
            "ix_review_queue_item_events_item_created",
            "review_queue_item_id",
            "created_at",
        ),
        Index(
            "ix_review_queue_item_events_queue_created",
            "review_queue_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    review_queue_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("review_queues.id", ondelete="CASCADE"),
        nullable=False,
    )
    review_queue_item_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("review_queue_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    client_request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    assignee: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
