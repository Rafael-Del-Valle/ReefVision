"""Verified instance or semantic mask annotation."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class MaskAnnotation(Base):
    __tablename__ = "mask_annotations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    image_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("images.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label_class_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("label_classes.id", ondelete="CASCADE"), nullable=True, index=True
    )
    geometry_kind: Mapped[str] = mapped_column(String(30), nullable=False, default="instance_mask")
    mask_path: Mapped[str | None] = mapped_column(String(700), nullable=True)
    polygon_json: Mapped[list[list[float]] | None] = mapped_column(JSON, nullable=True)
    x_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    y_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    x_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    y_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    area_pixels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False, default="human")
    provenance_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="verified")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
