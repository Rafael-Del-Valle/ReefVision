"""Persisted quality-control issues raised by a run."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now

if TYPE_CHECKING:
    from reefvision.db.models.project import Project
    from reefvision.db.models.quality_control_run import QualityControlRun


class QualityControlIssue(Base):
    """A recommendation or diagnostic finding raised by a QC rule."""

    __tablename__ = "quality_control_issues"
    __table_args__ = (
        Index("ix_quality_control_issues_run_status", "quality_control_run_id", "status"),
        Index("ix_quality_control_issues_run_severity", "quality_control_run_id", "severity"),
        Index("ix_quality_control_issues_run_rule", "quality_control_run_id", "rule_id"),
        Index("ix_quality_control_issues_project_image", "project_id", "image_id"),
        Index("ix_quality_control_issues_fingerprint", "fingerprint"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    quality_control_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("quality_control_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dataset_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    image_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    rule_id: Mapped[str] = mapped_column(String(100), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="open")
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    annotation_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    prediction_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    class_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    measured_values_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    thresholds_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    resolution_metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    dismissed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    quality_control_run: Mapped[QualityControlRun] = relationship(back_populates="issues")
    project: Mapped[Project] = relationship()
