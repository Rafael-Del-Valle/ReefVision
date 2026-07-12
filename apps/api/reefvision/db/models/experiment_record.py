"""Training experiment summaries for comparison views."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class ExperimentRecord(Base):
    """A completed training run distilled into a comparable experiment record."""

    __tablename__ = "experiment_records"
    __table_args__ = (
        UniqueConstraint("training_run_id", name="uq_experiment_records_training_run_id"),
        Index("ix_experiment_records_project_created", "project_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    training_run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("training_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dataset_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("dataset_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    dataset_manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    split_manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    task: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(100), nullable=False)
    architecture: Mapped[str] = mapped_column(String(200), nullable=False)
    summary_metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    comparison_warnings_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    artifact_manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    package_versions_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
