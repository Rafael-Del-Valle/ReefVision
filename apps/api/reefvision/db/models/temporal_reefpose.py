"""Persistence for frozen temporal pose datasets, prediction runs, and frame evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class TemporalReefPoseDataset(Base):
    __tablename__ = "temporal_reefpose_datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class TemporalReefPoseRun(Base):
    __tablename__ = "temporal_reefpose_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    dataset_id: Mapped[str | None] = mapped_column(
        ForeignKey("temporal_reefpose_datasets.id", ondelete="CASCADE")
    )
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    identity_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("pose_identity_association_runs.id", ondelete="SET NULL")
    )
    identity_id: Mapped[str | None] = mapped_column(
        ForeignKey("pose_animal_identities.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    configuration_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    input_manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    input_manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    review_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class TemporalReefPoseFrame(Base):
    __tablename__ = "temporal_reefpose_frames"
    __table_args__ = (
        UniqueConstraint("run_id", "frame_index", name="uq_temporal_reefpose_run_frame"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id: Mapped[str] = mapped_column(
        ForeignKey("temporal_reefpose_runs.id", ondelete="CASCADE"), index=True
    )
    frame_index: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    review_source: Mapped[str | None] = mapped_column(String(20))
