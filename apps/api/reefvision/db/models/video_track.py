"""Track annotations represented by sparse source-coordinate keyframes."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now

if TYPE_CHECKING:
    from reefvision.db.models.geo_referenced_observation import (
        GeoReferencedObservation,
    )


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
    keyframes_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    interpolation: Mapped[str] = mapped_column(String(30), nullable=False, default="linear")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    source_model_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("model_registrations.id", ondelete="SET NULL"), nullable=True
    )
    source_job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    geo_referenced_observations: Mapped[list[GeoReferencedObservation]] = relationship(
        back_populates="track",
        passive_deletes=True,
    )
