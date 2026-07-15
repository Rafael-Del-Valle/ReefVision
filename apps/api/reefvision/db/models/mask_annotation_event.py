"""Append-only mask-annotation history events."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now

if TYPE_CHECKING:
    from reefvision.db.models.image import ImageAsset
    from reefvision.db.models.mask_annotation import MaskAnnotation


class MaskAnnotationEvent(Base):
    """A persisted audit event describing a committed mask change."""

    __tablename__ = "mask_annotation_events"
    __table_args__ = (
        Index("ix_mask_annotation_events_annotation_created", "mask_annotation_id", "created_at"),
        Index("ix_mask_annotation_events_image_created", "image_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    mask_annotation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("mask_annotations.id", ondelete="CASCADE"), nullable=False
    )
    image_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("images.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    mask_annotation: Mapped[MaskAnnotation] = relationship(back_populates="events")
    image: Mapped[ImageAsset] = relationship()
