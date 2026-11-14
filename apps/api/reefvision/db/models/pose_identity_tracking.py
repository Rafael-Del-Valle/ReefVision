"""Canonical multi-animal pose identity persistence models."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
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


def _uuid() -> str:
    return str(uuid4())


class PoseIdentityAssociationRun(Base):
    """One reproducible association attempt over immutable pose detections."""

    __tablename__ = "pose_identity_association_runs"
    __table_args__ = (
        CheckConstraint("pose_schema_revision >= 1", name="ck_pose_identity_runs_schema_rev"),
        CheckConstraint("revision >= 1", name="ck_pose_identity_runs_revision"),
        Index("ix_pose_identity_runs_video_created", "video_id", "created_at"),
        Index("ix_pose_identity_runs_project_status", "project_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    video_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False
    )
    source_model_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("model_registrations.id", ondelete="SET NULL"), nullable=True
    )
    source_job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    pose_schema_id: Mapped[str] = mapped_column(String(200), nullable=False)
    pose_schema_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    pose_schema_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(100), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(50), nullable=False)
    parameters_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    parameters_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    input_manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_coordinate_space: Mapped[str] = mapped_column(
        String(30), nullable=False, default="source_pixels"
    )
    source_width: Mapped[int] = mapped_column(Integer, nullable=False)
    source_height: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    progress_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PoseAnimalIdentity(Base):
    """Stable identity scoped to one association run."""

    __tablename__ = "pose_animal_identities"
    __table_args__ = (
        UniqueConstraint("association_run_id", "stable_identity_key", name="uq_pose_identity_key"),
        CheckConstraint("first_frame >= 0", name="ck_pose_animal_identity_first_frame"),
        CheckConstraint(
            "last_frame IS NULL OR last_frame >= first_frame",
            name="ck_pose_animal_identity_frame_order",
        ),
        Index("ix_pose_animal_identity_run_frames", "association_run_id", "first_frame"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    association_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("pose_identity_association_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    stable_identity_key: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    origin: Mapped[str] = mapped_column(String(30), nullable=False, default="model")
    verification_state: Mapped[str] = mapped_column(
        String(30), nullable=False, default="unreviewed"
    )
    lifecycle_state: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    first_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    last_frame: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mean_association_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class PoseIdentityObservation(Base):
    """Immutable revision of a pose detection assigned to an animal identity."""

    __tablename__ = "pose_identity_observations"
    __table_args__ = (
        UniqueConstraint(
            "observation_series_id", "revision", name="uq_pose_identity_observation_revision"
        ),
        CheckConstraint("frame_index >= 0", name="ck_pose_identity_observation_frame"),
        CheckConstraint("revision >= 1", name="ck_pose_identity_observation_rev"),
        Index("ix_pose_identity_observation_run_frame", "association_run_id", "frame_index"),
        Index("ix_pose_identity_observation_identity_frame", "animal_identity_id", "frame_index"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    observation_series_id: Mapped[str] = mapped_column(String(36), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    supersedes_observation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("pose_identity_observations.id", ondelete="SET NULL"), nullable=True
    )
    association_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("pose_identity_association_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    animal_identity_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("pose_animal_identities.id", ondelete="SET NULL"), nullable=True
    )
    source_video_track_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("video_tracks.id", ondelete="RESTRICT"), nullable=False
    )
    source_detection_key: Mapped[str] = mapped_column(String(200), nullable=False)
    frame_index: Mapped[int] = mapped_column(Integer, nullable=False)
    time_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_json: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    landmarks_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    detection_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    association_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    visibility_state: Mapped[str] = mapped_column(String(30), nullable=False, default="visible")
    assignment_source: Mapped[str] = mapped_column(String(30), nullable=False, default="model")
    verification_state: Mapped[str] = mapped_column(
        String(30), nullable=False, default="unreviewed"
    )
    coordinate_space: Mapped[str] = mapped_column(
        String(30), nullable=False, default="source_pixels"
    )
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class PoseIdentityAssociationDecision(Base):
    """Every selected and rejected candidate retained for audit."""

    __tablename__ = "pose_identity_association_decisions"
    __table_args__ = (
        UniqueConstraint("observation_id", "candidate_rank", name="uq_pose_identity_decision_rank"),
        CheckConstraint("candidate_rank >= 1", name="ck_pose_identity_decision_rank"),
        Index("ix_pose_identity_decision_run_selected", "association_run_id", "selected"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    association_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("pose_identity_association_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    observation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pose_identity_observations.id", ondelete="CASCADE"), nullable=False
    )
    candidate_identity_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("pose_animal_identities.id", ondelete="SET NULL"), nullable=True
    )
    previous_observation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("pose_identity_observations.id", ondelete="SET NULL"), nullable=True
    )
    candidate_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    passed_gate: Mapped[bool] = mapped_column(Boolean, nullable=False)
    gate_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    total_cost: Mapped[float] = mapped_column(Float, nullable=False)
    acceptance_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    score_components_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    association_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    algorithm: Mapped[str] = mapped_column(String(100), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(50), nullable=False)
    parameters_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class PoseIdentityOcclusion(Base):
    __tablename__ = "pose_identity_occlusions"
    __table_args__ = (
        CheckConstraint("start_frame >= 0", name="ck_pose_identity_occlusion_start"),
        CheckConstraint(
            "end_frame IS NULL OR end_frame >= start_frame",
            name="ck_pose_identity_occlusion_order",
        ),
        Index("ix_pose_identity_occlusion_identity", "animal_identity_id", "start_frame"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    association_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("pose_identity_association_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    animal_identity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pose_animal_identities.id", ondelete="CASCADE"), nullable=False
    )
    start_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    end_frame: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(String(50), nullable=False, default="missed_detection")
    recovery_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class PoseIdentityCorrection(Base):
    """Append-only scientist correction event."""

    __tablename__ = "pose_identity_corrections"
    __table_args__ = (
        CheckConstraint("revision >= 1", name="ck_pose_identity_correction_revision"),
        Index("ix_pose_identity_correction_run_created", "association_run_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    association_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("pose_identity_association_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    target_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[str] = mapped_column(String(100), nullable=False)
    frame_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frame_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    before_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    after_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    before_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    after_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor: Mapped[str] = mapped_column(String(100), nullable=False, default="local_user")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class PoseIdentityTruthDataset(Base):
    """Immutable, hash-addressed scientist-verified identity truth."""

    __tablename__ = "pose_identity_truth_datasets"
    __table_args__ = (Index("ix_pose_identity_truth_video_created", "video_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    video_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    pose_schema_id: Mapped[str] = mapped_column(String(200), nullable=False)
    pose_schema_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    pose_schema_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    verification_state: Mapped[str] = mapped_column(String(30), nullable=False)
    verified_by: Mapped[str] = mapped_column(String(100), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class PoseIdentityEvaluationRun(Base):
    """Immutable scientific identity evaluation report."""

    __tablename__ = "pose_identity_evaluation_runs"
    __table_args__ = (
        Index("ix_pose_identity_eval_run_created", "association_run_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    association_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("pose_identity_association_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    association_run_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    truth_dataset_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("pose_identity_truth_datasets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    configuration_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    warnings_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
