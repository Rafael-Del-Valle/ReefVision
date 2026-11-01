"""Append-only, attributed but unauthenticated 3D calibration review receipts."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class SpatialCalibrationReviewRecord(Base):
    """Durable QC evidence, not verified scale, identity, or reviewer authentication."""

    __tablename__ = "spatial_calibration_reviews"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "spatial_source_asset_id",
            "evidence_sha256",
            name="uq_spatial_calibration_review_evidence",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    spatial_source_asset_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("spatial_source_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
