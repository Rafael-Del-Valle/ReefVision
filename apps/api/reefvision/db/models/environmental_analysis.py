"""Immutable definitions and snapshots for composite environmental analyses."""

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class EnvironmentalAnalysisDefinition(Base):
    __tablename__ = "environmental_analysis_definitions"
    __table_args__ = (
        Index(
            "ix_environmental_analysis_definition_project_kind",
            "project_id",
            "analysis_kind",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    analysis_kind: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(200))
    configuration_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    calculation_version: Mapped[str] = mapped_column(String(100))
    definition_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class EnvironmentalAnalysisResult(Base):
    __tablename__ = "environmental_analysis_results"
    __table_args__ = (
        Index(
            "ix_environmental_analysis_result_project_kind",
            "project_id",
            "analysis_kind",
            "created_at",
        ),
        Index("ix_environmental_analysis_result_definition", "definition_id", "created_at"),
        UniqueConstraint(
            "workflow_node_run_id",
            name="uq_environmental_analysis_result_workflow_node_run",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    definition_id: Mapped[str] = mapped_column(
        ForeignKey("environmental_analysis_definitions.id", ondelete="RESTRICT")
    )
    analysis_kind: Mapped[str] = mapped_column(String(50))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    input_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    source_record_ids_json: Mapped[list[str]] = mapped_column(JSON)
    source_analysis_result_ids_json: Mapped[list[str]] = mapped_column(JSON)
    quality_control_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    uncertainty_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    content_sha256: Mapped[str] = mapped_column(String(64))
    workflow_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="RESTRICT")
    )
    workflow_node_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_node_runs.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
