"""Immutable scientific pose evaluation runs."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class PoseEvaluationRun(Base):
    __tablename__ = "pose_evaluation_runs"
    __table_args__ = (
        Index("ix_pose_evaluation_project_created", "project_id", "created_at"),
        Index("ix_pose_evaluation_model_created", "model_id", "created_at"),
        Index("ix_pose_evaluation_dataset_created", "evaluation_dataset_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    model_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("model_registrations.id", ondelete="RESTRICT"), nullable=False
    )
    evaluation_dataset_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("pose_training_datasets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    schema_version: Mapped[str] = mapped_column(
        String(50), nullable=False, default="reefpose-evaluation-run-0001"
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="completed")
    configuration_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    predictions_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    warnings_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    result_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    inference_latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    images_per_second: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
