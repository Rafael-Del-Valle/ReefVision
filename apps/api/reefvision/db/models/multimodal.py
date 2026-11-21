"""Immutable paired optical and acoustic study receipts."""

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class MultimodalStudy(Base):
    __tablename__ = "multimodal_studies"
    __table_args__ = (
        UniqueConstraint("project_id", "operation_id", name="uq_multimodal_project_operation"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    operation_id: Mapped[str] = mapped_column(String(36))
    name: Mapped[str] = mapped_column(String(240))
    audio_report_id: Mapped[str] = mapped_column(
        ForeignKey("bioacoustic_reports.id", ondelete="RESTRICT")
    )
    role_revision_id: Mapped[str] = mapped_column(
        ForeignKey("reviewer_lab_role_revisions.id", ondelete="RESTRICT")
    )
    content_sha256: Mapped[str] = mapped_column(String(64))
    request_sha256: Mapped[str] = mapped_column(String(64))
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    source_id_map_json: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
