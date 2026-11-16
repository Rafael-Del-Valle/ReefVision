"""Append-only source-calibration snapshots attached to unverified ecological evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class EcologyIdentityCalibrationEvidence(Base):
    """Freeze a source image's saved calibration without certifying biological truth."""

    __tablename__ = "ecology_identity_calibration_evidence"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "annotation_evidence_id",
            name="uq_ecology_calibration_annotation_evidence",
        ),
        Index("ix_ecology_calibration_evidence_project_image", "project_id", "image_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    annotation_evidence_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ecology_identity_annotation_evidence.id", ondelete="RESTRICT"),
        nullable=False,
    )
    image_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("images.id", ondelete="RESTRICT"), nullable=False
    )
    image_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    calibration_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    calibration_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
