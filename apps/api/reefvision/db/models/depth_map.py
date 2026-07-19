"""Persisted depth map aligned to one managed image."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class DepthMap(Base):
    __tablename__ = "depth_maps"
    __table_args__ = (
        UniqueConstraint(
            "image_id",
            "provider_id",
            "model_id",
            "depth_kind",
            name="uq_depth_maps_image_provider_model_kind",
        ),
        UniqueConstraint("managed_path", name="uq_depth_maps_managed_path"),
        Index("ix_depth_maps_project_image", "project_id", "image_id"),
        Index("ix_depth_maps_sha256", "sha256"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    image_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("images.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider_id: Mapped[str] = mapped_column(String(120), nullable=False)
    model_id: Mapped[str] = mapped_column(String(500), nullable=False)
    model_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    depth_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    managed_path: Mapped[str] = mapped_column(String(800), nullable=False)
    preview_path: Mapped[str] = mapped_column(String(800), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    width_px: Mapped[int] = mapped_column(Integer, nullable=False)
    height_px: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_depth: Mapped[float] = mapped_column(Float, nullable=False)
    maximum_depth: Mapped[float] = mapped_column(Float, nullable=False)
    median_depth: Mapped[float] = mapped_column(Float, nullable=False)
    valid_pixel_count: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )
