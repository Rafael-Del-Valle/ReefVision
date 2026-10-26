"""Global idempotency registry for researcher-triggered QC bulk requests."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class ReviewQueueBulkRequestRecord(Base):
    """A committed batch identity, never scientific or model approval."""

    __tablename__ = "review_queue_bulk_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    review_queue_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("review_queues.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    item_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
