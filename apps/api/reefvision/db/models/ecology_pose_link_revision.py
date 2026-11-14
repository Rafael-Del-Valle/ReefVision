"""Append-only scientific review of links between ReefPose and organisms."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
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


class EcologyPoseLinkRevision(Base):
    __tablename__ = "ecology_pose_link_revisions"
    __table_args__ = (
        UniqueConstraint("link_id", "revision", name="uq_ecology_pose_link_revision"),
        CheckConstraint("revision >= 1", name="ck_ecology_pose_link_revision"),
        CheckConstraint(
            "frame_start >= 0 AND frame_end >= frame_start",
            name="ck_ecology_pose_link_frames",
        ),
        CheckConstraint(
            "action IN ('link', 'correct', 'unlink')", name="ck_ecology_pose_link_action"
        ),
        Index("ix_ecology_pose_link_project", "project_id", "link_id", "revision"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    link_id: Mapped[str] = mapped_column(String(36), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(12), nullable=False)
    supersedes_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("ecology_pose_link_revisions.id", ondelete="RESTRICT")
    )
    organism_revision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ecology_identity_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    association_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("pose_identity_association_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    animal_identity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pose_animal_identities.id", ondelete="RESTRICT"), nullable=False
    )
    frame_start: Mapped[int] = mapped_column(Integer, nullable=False)
    frame_end: Mapped[int] = mapped_column(Integer, nullable=False)
    source_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    reviewer: Mapped[str] = mapped_column(String(100), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
