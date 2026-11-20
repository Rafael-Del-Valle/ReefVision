"""Immutable image adjustment receipt with a live project/image binding."""

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class ImageAdjustmentRecipe(Base):
    __tablename__ = "image_adjustment_recipes"
    __table_args__ = (
        UniqueConstraint("image_id", "content_sha256", name="uq_image_adjustment_receipt"),
        Index("ix_image_adjustments_project", "project_id", "image_id", "created_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    image_id: Mapped[str] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"))
    content_sha256: Mapped[str] = mapped_column(String(64))
    receipt_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
