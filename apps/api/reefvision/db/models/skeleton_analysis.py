"""Persisted coral skeleton analysis revisions and review state."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class SkeletonAnalysisRevision(Base):
    """Immutable automatic or human-corrected skeleton analysis snapshot."""

    __tablename__ = "skeleton_analysis_revisions"
    __table_args__ = (
        CheckConstraint(
            "analysis_revision >= 1",
            name="ck_skeleton_analysis_revisions_revision",
        ),
        CheckConstraint(
            "mask_revision >= 1",
            name="ck_skeleton_analysis_revisions_mask_revision",
        ),
        CheckConstraint(
            "terminal_spur_max_length_pixels >= 0",
            name="ck_skeleton_analysis_revisions_spur_threshold",
        ),
        UniqueConstraint(
            "analysis_series_id",
            "analysis_revision",
            name="uq_skeleton_analysis_series_revision",
        ),
        Index(
            "ix_skeleton_analysis_mask_revision",
            "mask_annotation_id",
            "mask_revision",
            "created_at",
        ),
        Index(
            "ix_skeleton_analysis_series_revision",
            "analysis_series_id",
            "analysis_revision",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    analysis_series_id: Mapped[str] = mapped_column(String(36), nullable=False)
    analysis_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    supersedes_analysis_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("skeleton_analysis_revisions.id", ondelete="SET NULL"),
        nullable=True,
    )
    mask_annotation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("mask_annotations.id", ondelete="CASCADE"),
        nullable=False,
    )
    image_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("images.id", ondelete="CASCADE"),
        nullable=False,
    )
    mask_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    source_kind: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="automatic",
    )
    algorithm: Mapped[str] = mapped_column(String(60), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(40), nullable=False)
    terminal_spur_max_length_pixels: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
    )
    input_mask_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    calibration_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parameters_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    result_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    correction_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    review_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="unreviewed",
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="local_user",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
