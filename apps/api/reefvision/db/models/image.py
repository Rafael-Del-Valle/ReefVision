"""Managed project image database model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now

if TYPE_CHECKING:
    from reefvision.db.models.annotation import Annotation
    from reefvision.db.models.mask_annotation import MaskAnnotation
    from reefvision.db.models.prediction_proposal import PredictionProposal
    from reefvision.db.models.project import Project


class ImageAsset(Base):
    """An immutable managed copy of an imported source image."""

    __tablename__ = "images"
    __table_args__ = (
        UniqueConstraint("project_id", "sha256", name="uq_images_project_sha256"),
        Index("ix_images_project_status", "project_id", "annotation_status"),
        Index("ix_images_project_group_key", "project_id", "group_key"),
        Index("ix_images_project_sequence", "project_id", "created_at", "id"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    managed_path: Mapped[str] = mapped_column(String(700), nullable=False, unique=True)
    thumbnail_path: Mapped[str | None] = mapped_column(String(700), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    width_px: Mapped[int] = mapped_column(Integer, nullable=False)
    height_px: Mapped[int] = mapped_column(Integer, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    import_source: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    capture_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    group_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    annotation_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="unannotated"
    )
    annotation_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    project: Mapped[Project] = relationship(back_populates="images")
    annotations: Mapped[list[Annotation]] = relationship(
        back_populates="image", cascade="all, delete-orphan"
    )
    mask_annotations: Mapped[list[MaskAnnotation]] = relationship(
        back_populates="image", cascade="all, delete-orphan"
    )
    prediction_proposals: Mapped[list[PredictionProposal]] = relationship(
        back_populates="image", cascade="all, delete-orphan"
    )
