"""Immutable reviewed coral graph, correspondence, and measurement records."""

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class _Snapshot:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    content_sha256: Mapped[str] = mapped_column(String(64))
    source_id_map_json: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class _Review:
    reviewer: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(String(500))
    revision: Mapped[int] = mapped_column(Integer)


class CoralGraphRevision(_Snapshot, _Review, Base):
    __tablename__ = "coral_graph_revisions"
    __table_args__ = (UniqueConstraint("graph_id", "revision", name="uq_coral_graph_revision"),)

    graph_id: Mapped[str] = mapped_column(String(36), index=True)
    identity_revision_id: Mapped[str] = mapped_column(
        ForeignKey("ecology_identity_revisions.id", ondelete="RESTRICT")
    )
    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("skeleton_analysis_revisions.id", ondelete="RESTRICT"), index=True
    )
    supersedes_id: Mapped[str | None] = mapped_column(
        ForeignKey("coral_graph_revisions.id", ondelete="RESTRICT")
    )
    decision: Mapped[str] = mapped_column(String(12))


class CoralBranchCorrespondenceRevision(_Snapshot, _Review, Base):
    __tablename__ = "coral_branch_correspondence_revisions"
    __table_args__ = (
        UniqueConstraint("correspondence_id", "revision", name="uq_coral_correspondence_revision"),
    )

    correspondence_id: Mapped[str] = mapped_column(String(36), index=True)
    earlier_graph_revision_id: Mapped[str] = mapped_column(
        ForeignKey("coral_graph_revisions.id", ondelete="RESTRICT")
    )
    later_graph_revision_id: Mapped[str] = mapped_column(
        ForeignKey("coral_graph_revisions.id", ondelete="RESTRICT")
    )
    supersedes_id: Mapped[str | None] = mapped_column(
        ForeignKey("coral_branch_correspondence_revisions.id", ondelete="RESTRICT")
    )


class CoralGrowthRecord(_Snapshot, Base):
    __tablename__ = "coral_growth_records"

    correspondence_revision_id: Mapped[str] = mapped_column(
        ForeignKey("coral_branch_correspondence_revisions.id", ondelete="RESTRICT"), index=True
    )
