"""Immutable computed metric definitions and result snapshots."""

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class ComputedMetricDefinition(Base):
    __tablename__ = "computed_metric_definitions"
    __table_args__ = (Index("ix_computed_metric_definition_project", "project_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    expression: Mapped[str] = mapped_column(String(1000))
    formula_version: Mapped[str] = mapped_column(String(100))
    input_spec_json: Mapped[list[dict[str, str]]] = mapped_column(JSON)
    output_unit: Mapped[str] = mapped_column(String(50))
    definition_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ComputedMetricResult(Base):
    __tablename__ = "computed_metric_results"
    __table_args__ = (
        Index("ix_computed_metric_result_project", "project_id", "created_at"),
        UniqueConstraint(
            "workflow_node_run_id", name="uq_computed_metric_result_workflow_node_run"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    definition_id: Mapped[str] = mapped_column(
        ForeignKey("computed_metric_definitions.id", ondelete="RESTRICT")
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    content_sha256: Mapped[str] = mapped_column(String(64))
    workflow_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="RESTRICT")
    )
    workflow_node_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_node_runs.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
