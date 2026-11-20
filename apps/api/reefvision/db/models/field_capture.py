"""Persist local batches, immutable observations and their review evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class FieldCaptureBatch(Base):
    __tablename__ = "field_capture_batches"
    __table_args__ = (
        UniqueConstraint("project_id", "manifest_sha256", name="uq_field_batch_project_manifest"),
        Index("ix_field_capture_batches_project", "project_id", "created_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    origin_project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    origin_batch_id: Mapped[str] = mapped_column(String(36), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    manifest_sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class FieldCaptureObservation(Base):
    __tablename__ = "field_capture_observations"
    __table_args__ = (
        UniqueConstraint("batch_id", "source_observation_id", name="uq_field_batch_observation"),
        UniqueConstraint("batch_id", "ordinal", name="uq_field_batch_ordinal"),
        Index("ix_field_observation_project_source", "project_id", "source_observation_id"),
        Index("ix_field_observation_project_claim", "project_id", "claim_key"),
        Index("ix_field_observation_project_media", "project_id", "kind", "sha256"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    batch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("field_capture_batches.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source_observation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    managed_path: Mapped[str] = mapped_column(String(700), nullable=False)
    claim_key: Mapped[str | None] = mapped_column(String(600))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class FieldCaptureReconciliationRecord(Base):
    __tablename__ = "field_capture_reconciliations"

    batch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("field_capture_batches.id", ondelete="CASCADE"), primary_key=True
    )
    report_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    report_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class FieldCaptureReview(Base):
    __tablename__ = "field_capture_reviews"
    __table_args__ = (
        UniqueConstraint("observation_id", "against_observation_id", name="uq_field_review_pair"),
        Index("ix_field_capture_reviews_batch", "batch_id", "created_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    batch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("field_capture_batches.id", ondelete="CASCADE"), nullable=False
    )
    observation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("field_capture_observations.id", ondelete="CASCADE"), nullable=False
    )
    against_observation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("field_capture_observations.id", ondelete="CASCADE"), nullable=False
    )
    reviewer: Mapped[str] = mapped_column(String(200), nullable=False)
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    notes: Mapped[str] = mapped_column(String(2000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
