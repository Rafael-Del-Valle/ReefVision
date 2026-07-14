"""Track annotations represented by sparse keyframes."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class VideoTrack(Base):
    __tablename__ = "video_tracks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    video_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label_class_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("label_classes.id", ondelete="RESTRICT"), nullable=False
    )
    track_number: Mapped[int] = mapped_column(Integer, nullable=False)
    geometry_kind: Mapped[str] = mapped_column(String(30), nullable=False, default="bbox")
    # [{"frame": 0, "bbox": [x, y, w, h]}, {"frame": 12, "bbox": [...]}]
    keyframes_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    interpolation: Mapped[str] = mapped_column(String(30), nullable=False, default="linear")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
