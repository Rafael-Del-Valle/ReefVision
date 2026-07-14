"""Image-level classification label."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class ImageLabel(Base):
    __tablename__ = "image_labels"
    __table_args__ = (
        UniqueConstraint(
            "image_id",
            "label_class_id",
            "label_set",
            name="uq_image_labels_image_class_set",
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
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="verified")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
