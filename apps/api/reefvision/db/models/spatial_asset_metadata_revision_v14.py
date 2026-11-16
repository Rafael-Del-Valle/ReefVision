"""Append-only coordinate/calibration metadata revisions for 3D source assets."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class SpatialAssetMetadataRevision(Base):
    __tablename__ = "spatial_asset_metadata_revisions"
    __table_args__ = (
        UniqueConstraint(
            "spatial_source_asset_id",
            "revision",
            name="uq_spatial_asset_metadata_revision",
        ),
        UniqueConstraint(
            "spatial_source_asset_id",
            "content_sha256",
            name="uq_spatial_asset_metadata_content",
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
    previous_revision_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("spatial_asset_metadata_revisions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    coordinate_unit: Mapped[str] = mapped_column(String(32), nullable=False)
    meters_per_unit: Mapped[float | None] = mapped_column(Float, nullable=True)
    coordinate_frame_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    transform_to_project_frame_json: Mapped[list[list[float]] | None] = mapped_column(
        JSON, nullable=True
    )
    calibration_evidence: Mapped[str | None] = mapped_column(String(2_000), nullable=True)
    review_state: Mapped[str] = mapped_column(String(40), nullable=False)
    reviewed_by_identity: Mapped[str | None] = mapped_column(String(128), nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(2_000), nullable=True)
    created_by_identity: Mapped[str] = mapped_column(String(128), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    @property
    def transform_to_project_frame(self) -> list[list[float]] | None:
        return self.transform_to_project_frame_json
