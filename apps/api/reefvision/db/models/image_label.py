"""Revisioned image-level classification label."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class ImageLabel(Base):
    __tablename__ = "image_labels"
    __table_args__ = (
        UniqueConstraint(
            "image_id", "label_class_id", "label_set", name="uq_image_labels_image_class_set"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    image_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("images.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label_class_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("label_classes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label_set: Mapped[str] = mapped_column(String(100), nullable=False, default="default")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False, default="human")
    source_model_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_prediction_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    provenance_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="verified")
    created_by: Mapped[str] = mapped_column(String(100), nullable=False, default="local_user")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
