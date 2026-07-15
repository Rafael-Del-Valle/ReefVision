"""Immutable dataset-version snapshot database model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now

if TYPE_CHECKING:
    from reefvision.db.models.dataset_version_item import DatasetVersionItem
    from reefvision.db.models.export_record import ExportRecord
    from reefvision.db.models.project import Project


class DatasetVersion(Base):
    """An immutable snapshot of a project's eligible images and annotations."""

    __tablename__ = "dataset_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "version_number", name="uq_dataset_versions_project_number"),
        Index("ix_dataset_versions_project_status", "project_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("dataset_versions.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="creating")
    requested_split_method: Mapped[str] = mapped_column(String(30), nullable=False)
    resolved_split_method: Mapped[str] = mapped_column(String(30), nullable=False)
    eligible_annotation_statuses_json: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    requested_ratios_json: Mapped[dict[str, float] | None] = mapped_column(JSON, nullable=True)
    achieved_ratios_json: Mapped[dict[str, float] | None] = mapped_column(JSON, nullable=True)
    split_seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reuse_parent_assignments: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    missing_group_key_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warnings_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    class_map_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    image_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    annotation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mask_annotation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False, default="local_user")
    reefvision_version: Mapped[str] = mapped_column(String(30), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[Project] = relationship(back_populates="dataset_versions")
    parent_version: Mapped[DatasetVersion | None] = relationship(
        remote_side="DatasetVersion.id",
        back_populates="child_versions",
    )
    child_versions: Mapped[list[DatasetVersion]] = relationship(back_populates="parent_version")
    items: Mapped[list[DatasetVersionItem]] = relationship(
        back_populates="dataset_version",
        cascade="all, delete-orphan",
        order_by="DatasetVersionItem.created_at",
    )
    exports: Mapped[list[ExportRecord]] = relationship(
        back_populates="dataset_version",
        cascade="all, delete-orphan",
        order_by="ExportRecord.created_at",
    )
