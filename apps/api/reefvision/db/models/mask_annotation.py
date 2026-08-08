"""Verified instance or semantic mask annotation."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now

if TYPE_CHECKING:
    from reefvision.db.models.image import ImageAsset
    from reefvision.db.models.label_class import LabelClass
    from reefvision.db.models.mask_annotation_event import MaskAnnotationEvent


class MaskAnnotation(Base):
    """A canonical source-pixel polygon or raster mask annotation."""

    __tablename__ = "mask_annotations"
    __table_args__ = (
        Index("ix_mask_annotations_image_deleted", "image_id", "deleted_at"),
        Index(
            "ix_mask_annotations_image_label_deleted",
            "image_id",
            "label_class_id",
            "deleted_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    image_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("images.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label_class_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("label_classes.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    geometry_kind: Mapped[str] = mapped_column(String(30), nullable=False, default="instance_mask")
    mask_path: Mapped[str | None] = mapped_column(String(700), nullable=True)
    polygon_json: Mapped[list[list[float]] | None] = mapped_column(JSON, nullable=True)
    x_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    y_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    x_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    y_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    area_pixels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    measurement_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False, default="human")
    provenance_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="verified")
    created_by: Mapped[str] = mapped_column(String(100), nullable=False, default="local_user")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    image: Mapped[ImageAsset] = relationship(back_populates="mask_annotations")
    label_class: Mapped[LabelClass | None] = relationship(back_populates="mask_annotations")
    events: Mapped[list[MaskAnnotationEvent]] = relationship(
        back_populates="mask_annotation", cascade="all, delete-orphan"
    )
