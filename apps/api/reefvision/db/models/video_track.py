"""Track annotations represented by sparse keyframes."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class VideoTrack(Base):
    __tablename__ = "video_tracks"
    __table_args__ = (Index("ix_video_tracks_video_number", "video_id", "track_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    video_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label_class_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("label_classes.id", ondelete="RESTRICT"), nullable=True
    )
    origin_job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    track_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    geometry_kind: Mapped[str] = mapped_column(String(30), nullable=False, default="bounding_box")
    keyframes_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    interpolation: Mapped[str] = mapped_column(String(30), nullable=False, default="linear")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    source_type: Mapped[str] = mapped_column(String(30), nullable=False, default="human")
    is_ground_truth: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False, default="local_user")
    updated_by: Mapped[str] = mapped_column(String(100), nullable=False, default="local_user")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
