"""Immutable ecological results and their explicitly reviewed selections."""

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class EcologyAnalysisRecord(Base):
    __tablename__ = "ecology_analysis_records"
    __table_args__ = (
        CheckConstraint("kind IN ('growth','abundance')", name="ck_ecology_analysis_kind"),
        Index("ix_ecology_analysis_project_created", "project_id", "created_at"),
        Index("ix_ecology_analysis_supersedes", "supersedes_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    supersedes_id: Mapped[str | None] = mapped_column(
        ForeignKey("ecology_analysis_records.id", ondelete="RESTRICT")
    )
    kind: Mapped[str] = mapped_column(String(20))
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    source_id_map_json: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    content_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
