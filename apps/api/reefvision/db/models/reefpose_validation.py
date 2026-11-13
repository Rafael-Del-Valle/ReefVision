"""Frozen reference revisions for independent ReefPose validation."""

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class ReefPoseReference(Base):
    __tablename__ = "reefpose_references"
    __table_args__ = (
        Index("ix_reefpose_references_project_created", "project_id", "created_at"),
        UniqueConstraint("parent_id", name="uq_reefpose_references_parent"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("reefpose_references.id", ondelete="CASCADE")
    )
    revision: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(200))
    data_kind: Mapped[str] = mapped_column(String(20))
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON)
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
