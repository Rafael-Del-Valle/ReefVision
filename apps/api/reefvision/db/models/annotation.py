"""Verified annotation database model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now

if TYPE_CHECKING:
    from reefvision.db.models.annotation_event import AnnotationEvent
    from reefvision.db.models.image import ImageAsset
    from reefvision.db.models.label_class import LabelClass


class Annotation(Base):
    """A canonical source-pixel bounding-box annotation."""

    __tablename__ = "annotations"
    __table_args__ = (
        Index("ix_annotations_image_deleted", "image_id", "deleted_at"),
        Index("ix_annotations_image_label_deleted", "image_id", "label_class_id", "deleted_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    image_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("images.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label_class_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("label_classes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    x_min: Mapped[float] = mapped_column(Float, nullable=False)
    y_min: Mapped[float] = mapped_column(Float, nullable=False)
    x_max: Mapped[float] = mapped_column(Float, nullable=False)
    y_max: Mapped[float] = mapped_column(Float, nullable=False)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False, default="human")
    source_model_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_prediction_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    provenance_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False, default="local_user")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    image: Mapped[ImageAsset] = relationship(back_populates="annotations")
    label_class: Mapped[LabelClass] = relationship(back_populates="annotations")
    events: Mapped[list[AnnotationEvent]] = relationship(
        back_populates="annotation", cascade="all, delete-orphan"
    )
