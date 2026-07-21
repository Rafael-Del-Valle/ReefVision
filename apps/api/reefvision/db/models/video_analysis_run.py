"""Persisted deterministic video-behavior analysis summaries."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class VideoAnalysisRun(Base):
    __tablename__ = "video_analysis_runs"
    __table_args__ = (
        Index("ix_video_analysis_runs_video_created", "video_id", "created_at"),
        Index("ix_video_analysis_runs_checksum", "result_sha256"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    video_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    configuration_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    source_revisions_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
