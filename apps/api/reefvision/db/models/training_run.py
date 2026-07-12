"""Persisted Training workspace execution records."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class TrainingRun(Base):
    """A queued or executed training run launched from a draft snapshot."""

    __tablename__ = "training_runs"
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_training_runs_job_id"),
        Index("ix_training_runs_project_created", "project_id", "created_at"),
        Index("ix_training_runs_project_status", "project_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    draft_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("training_drafts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    dataset_version_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("dataset_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    dataset_manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    split_manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    task: Mapped[str] = mapped_column(String(40), nullable=False)
    catalog_model_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    provider_id: Mapped[str] = mapped_column(String(100), nullable=False)
    architecture: Mapped[str] = mapped_column(String(200), nullable=False)
    initial_checkpoint_source: Mapped[str] = mapped_column(String(30), nullable=False)
    initial_checkpoint_model_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("model_registrations.id", ondelete="SET NULL"), nullable=True
    )
    resolved_model_asset_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_model_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parameter_registry_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    selected_preset: Mapped[str | None] = mapped_column(String(200), nullable=True)
    installation_state: Mapped[str | None] = mapped_column(String(40), nullable=True)
    device: Mapped[str] = mapped_column(String(60), nullable=False)
    precision: Mapped[str] = mapped_column(String(30), nullable=False)
    run_name: Mapped[str] = mapped_column(String(200), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    random_seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tiling_config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    training_config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    tuning_config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    evaluation_config_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    resource_limits_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    preflight_report_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    draft_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="queued")
    stage: Mapped[str] = mapped_column(String(60), nullable=False, default="queued")
    progress_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_total_epochs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    metrics_history_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    warnings_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    artifact_manifest_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    logs_path: Mapped[str | None] = mapped_column(String(700), nullable=True)
    result_checkpoint_path: Mapped[str | None] = mapped_column(String(700), nullable=True)
    job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
