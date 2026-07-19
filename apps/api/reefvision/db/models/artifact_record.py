"""Unified produced-artifact provenance model."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class ArtifactRecord(Base):
    __tablename__ = "artifact_records"
    __table_args__ = (
        Index(
            "ix_artifact_records_project_type_created",
            "project_id",
            "artifact_type",
            "created_at",
        ),
        Index("ix_artifact_records_checksum", "checksum"),
        Index("ix_artifact_records_source", "source_kind", "source_id"),
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
    )
    artifact_type: Mapped[str] = mapped_column(String(100), nullable=False)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False, default="system")
    reefvision_version: Mapped[str] = mapped_column(String(60), nullable=False)
    source_kind: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_annotation_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dataset_version_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("dataset_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    dataset_version_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("model_registrations.id", ondelete="SET NULL"),
        nullable=True,
    )
    model_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provider_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    parameters_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    postprocessing_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    review_status: Mapped[str] = mapped_column(String(40), nullable=False, default="unreviewed")
    parent_artifact_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("artifact_records.id", ondelete="SET NULL"),
        nullable=True,
    )
    supersedes_artifact_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("artifact_records.id", ondelete="SET NULL"),
        nullable=True,
    )
    managed_path: Mapped[str | None] = mapped_column(String(800), nullable=True)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
