"""Project study design declarations and binding revisions."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class StudyDesignRevision(Base):
    __tablename__ = "study_design_revisions"
    __table_args__ = (
        UniqueConstraint("project_id", "design_id", "revision", name="uq_study_design_revision"),
        Index("ix_study_design_project_created", "project_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE")
    )
    design_id: Mapped[str] = mapped_column(String(36))
    revision: Mapped[int] = mapped_column(Integer)
    supersedes_revision_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("study_design_revisions.id", ondelete="CASCADE"), unique=True
    )
    growth_analysis_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("ecology_analysis_records.id", ondelete="RESTRICT")
    )
    growth_source_sha256: Mapped[str | None] = mapped_column(String(64))
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    content_sha256: Mapped[str] = mapped_column(String(64))
    source_id_map_json: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
