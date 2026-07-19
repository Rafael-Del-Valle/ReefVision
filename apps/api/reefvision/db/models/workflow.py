"""Persisted workflow definitions, immutable revisions, runs, and artifacts."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class Workflow(Base):
    __tablename__ = "workflows"
    __table_args__ = (Index("ix_workflows_project_status", "project_id", "status"),)

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    current_revision_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False, default="local_user")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


class WorkflowRevision(Base):
    __tablename__ = "workflow_revisions"
    __table_args__ = (
        UniqueConstraint(
            "workflow_id",
            "revision_number",
            name="uq_workflow_revisions_workflow_number",
        ),
        Index("ix_workflow_revisions_checksum", "workflow_checksum"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    workflow_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    workflow_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    workflow_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    validation_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False, default="local_user")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (Index("ix_workflow_runs_project_status", "project_id", "status"),)

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    workflow_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
    )
    workflow_revision_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("workflow_revisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    stage: Mapped[str] = mapped_column(String(100), nullable=False, default="queued")
    current_node_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    node_state_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkflowArtifact(Base):
    __tablename__ = "workflow_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "workflow_run_id",
            "node_id",
            "port_name",
            name="uq_workflow_artifacts_run_node_port",
        ),
        Index("ix_workflow_artifacts_checksum", "checksum"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    workflow_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    node_id: Mapped[str] = mapped_column(String(100), nullable=False)
    port_name: Mapped[str] = mapped_column(String(100), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(100), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    managed_path: Mapped[str | None] = mapped_column(String(800), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
