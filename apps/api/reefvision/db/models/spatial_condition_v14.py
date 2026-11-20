"""Frozen condition rubrics and append-only project-owned condition history."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class SpatialConditionRubric(Base):
    __tablename__ = "spatial_condition_rubrics"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    rubric_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    version: Mapped[str] = mapped_column(String(128), primary_key=True)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class SpatialConditionRevision(Base):
    __tablename__ = "spatial_condition_revisions"
    __table_args__ = (Index("ix_spatial_condition_asset", "project_id", "asset_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    asset_id: Mapped[str] = mapped_column(
        ForeignKey("spatial_source_assets.id", ondelete="CASCADE")
    )
    observation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    previous_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("spatial_condition_revisions.id", ondelete="CASCADE"), unique=True
    )
    phase: Mapped[str] = mapped_column(String(16), nullable=False)
    observation_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    decision_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
