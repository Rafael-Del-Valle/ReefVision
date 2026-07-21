"""Append-only audit history for video-track corrections."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class VideoTrackEvent(Base):
    __tablename__ = "video_track_events"
    __table_args__ = (
        Index("ix_video_track_events_track_created", "video_track_id", "created_at"),
        Index("ix_video_track_events_video_created", "video_id", "created_at"),
        UniqueConstraint("operation_id", name="uq_video_track_events_operation_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    video_track_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("video_tracks.id", ondelete="CASCADE"), nullable=False
    )
    video_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    operation_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    actor: Mapped[str] = mapped_column(String(100), nullable=False, default="local_user")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
