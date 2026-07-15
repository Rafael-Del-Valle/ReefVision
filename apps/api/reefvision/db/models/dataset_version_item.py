"""Immutable per-image dataset-version snapshot model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now

if TYPE_CHECKING:
    from reefvision.db.models.dataset_version import DatasetVersion


class DatasetVersionItem(Base):
    """A frozen image membership record within one dataset version."""

    __tablename__ = "dataset_version_items"
    __table_args__ = (
        UniqueConstraint(
            "dataset_version_id", "image_id", name="uq_dataset_version_items_version_image"
        ),
        Index("ix_dataset_version_items_version_split", "dataset_version_id", "split"),
        Index("ix_dataset_version_items_version_group", "dataset_version_id", "group_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    dataset_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("dataset_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    image_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("images.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    image_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    width_px: Mapped[int] = mapped_column(Integer, nullable=False)
    height_px: Mapped[int] = mapped_column(Integer, nullable=False)
    image_annotation_status: Mapped[str] = mapped_column(String(30), nullable=False)
    split: Mapped[str] = mapped_column(String(20), nullable=False, default="unassigned")
    group_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    annotation_snapshot_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    mask_annotation_snapshot_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    per_class_counts_json: Mapped[dict[str, int]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    per_mask_class_counts_json: Mapped[dict[str, int]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    annotation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mask_annotation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    dataset_version: Mapped[DatasetVersion] = relationship(back_populates="items")
