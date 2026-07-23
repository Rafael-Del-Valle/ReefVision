"""Immutable whole-image, mask, and fragment classification datasets."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class ClassificationDatasetSnapshot(Base):
    __tablename__ = "classification_dataset_snapshots"
    __table_args__ = (
        Index(
            "ix_classification_dataset_snapshots_project_target_created",
            "project_id",
            "target_kind",
            "created_at",
        ),
        Index(
            "ix_classification_dataset_snapshots_label_set_status",
            "label_set_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label_set_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("classification_label_sets.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="complete")
    target_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    cardinality: Mapped[str] = mapped_column(String(20), nullable=False)
    split_seed: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_ratios_json: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)
    achieved_ratios_json: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)
    class_map_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    target_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    class_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warnings_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False, default="local_user")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ClassificationDatasetSample(Base):
    __tablename__ = "classification_dataset_samples"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "target_key",
            name="uq_classification_dataset_samples_snapshot_target",
        ),
        Index(
            "ix_classification_dataset_samples_snapshot_split",
            "snapshot_id",
            "split",
        ),
        Index(
            "ix_classification_dataset_samples_snapshot_group",
            "snapshot_id",
            "group_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    snapshot_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("classification_dataset_snapshots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    target_key: Mapped[str] = mapped_column(String(500), nullable=False)
    image_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("images.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    mask_annotation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("mask_annotations.id", ondelete="RESTRICT"), nullable=True
    )
    fragment_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    split: Mapped[str] = mapped_column(String(20), nullable=False)
    group_key: Mapped[str] = mapped_column(String(300), nullable=False)
    label_class_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    assignment_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    assignment_revisions_json: Mapped[dict[str, int]] = mapped_column(JSON, nullable=False)
    source_image_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_image_managed_path: Mapped[str] = mapped_column(String(700), nullable=False)
    source_image_width_px: Mapped[int] = mapped_column(Integer, nullable=False)
    source_image_height_px: Mapped[int] = mapped_column(Integer, nullable=False)
    target_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    geometry_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    sample_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
