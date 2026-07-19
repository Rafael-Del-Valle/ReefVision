"""Persisted immutable classification crop metadata."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class ClassificationCrop(Base):
    """A generated crop registered from a successful classification export."""

    __tablename__ = "classification_crops"
    __table_args__ = (
        UniqueConstraint(
            "export_id",
            "managed_path",
            name="uq_classification_crops_export_path",
        ),
        Index(
            "ix_classification_crops_project_class",
            "project_id",
            "label_class_id",
        ),
        Index(
            "ix_classification_crops_export_split",
            "export_id",
            "split",
        ),
        Index("ix_classification_crops_sha256", "sha256"),
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
    export_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("exports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dataset_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("dataset_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    image_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("images.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    annotation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    label_class_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("label_classes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    split: Mapped[str] = mapped_column(String(20), nullable=False)
    managed_path: Mapped[str] = mapped_column(String(800), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_box_json: Mapped[dict[str, float]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    crop_box_json: Mapped[dict[str, int]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
