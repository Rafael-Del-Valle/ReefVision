"""Immutable anatomical measurement and biological event persistence."""

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


class PoseMeasurementRun(Base):
    __tablename__ = "pose_measurement_runs"
    __table_args__ = (
        CheckConstraint(
            "source_identity_run_revision >= 1", name="ck_pose_measurement_identity_revision"
        ),
        CheckConstraint("revision >= 1", name="ck_pose_measurement_revision"),
        Index("ix_pose_measurement_run_video_created", "video_id", "created_at"),
        Index("ix_pose_measurement_run_status", "project_id", "status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    video_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("videos.id", ondelete="RESTRICT"), nullable=False
    )
    source_identity_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("pose_identity_association_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_identity_run_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    source_job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="SET NULL")
    )
    pose_schema_id: Mapped[str] = mapped_column(String(200), nullable=False)
    pose_schema_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    pose_schema_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    video_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    video_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    calibration_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    calibration_sha256: Mapped[str | None] = mapped_column(String(64))
    timebase_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    definitions_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    configuration_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    input_manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    input_manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    progress_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result_sha256: Mapped[str | None] = mapped_column(String(64))
    verification_state: Mapped[str] = mapped_column(
        String(30), nullable=False, default="exploratory"
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PoseMeasurementSeries(Base):
    __tablename__ = "pose_measurement_series"
    __table_args__ = (
        UniqueConstraint(
            "measurement_run_id",
            "animal_identity_id",
            "definition_id",
            name="uq_pose_measurement_series_definition",
        ),
        Index(
            "ix_pose_measurement_series_run_identity", "measurement_run_id", "animal_identity_id"
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    measurement_run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pose_measurement_runs.id", ondelete="CASCADE"), nullable=False
    )
    animal_identity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pose_animal_identities.id", ondelete="RESTRICT"), nullable=False
    )
    definition_id: Mapped[str] = mapped_column(String(100), nullable=False)
    measurement_kind: Mapped[str] = mapped_column(String(50), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    landmark_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    formula_version: Mapped[str] = mapped_column(String(50), nullable=False)
    unit_dimension: Mapped[str] = mapped_column(String(30), nullable=False)
    pixel_unit: Mapped[str] = mapped_column(String(30), nullable=False)
    physical_unit: Mapped[str | None] = mapped_column(String(30))
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    series_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class PoseMeasurementSample(Base):
    __tablename__ = "pose_measurement_samples"
    __table_args__ = (
        UniqueConstraint("series_id", "frame_index", name="uq_pose_measurement_sample_frame"),
        Index("ix_pose_measurement_sample_series_time", "series_id", "time_s"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    series_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pose_measurement_series.id", ondelete="CASCADE"), nullable=False
    )
    frame_index: Mapped[int] = mapped_column(Integer, nullable=False)
    time_s: Mapped[float] = mapped_column(Float, nullable=False)
    pixel_value: Mapped[float | None] = mapped_column(Float)
    physical_value: Mapped[float | None] = mapped_column(Float)
    value_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    confidence: Mapped[float | None] = mapped_column(Float)
    valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    quality_flags_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    source_observation_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source_observation_revisions_json: Mapped[list[int]] = mapped_column(JSON, nullable=False)


class PoseEventDetectionRun(Base):
    __tablename__ = "pose_event_detection_runs"
    __table_args__ = (
        Index("ix_pose_event_detection_measurement", "measurement_run_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    measurement_run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pose_measurement_runs.id", ondelete="RESTRICT"), nullable=False
    )
    source_job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="SET NULL")
    )
    configuration_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    configuration_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    progress_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result_sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PoseBiologicalEventRevision(Base):
    __tablename__ = "pose_biological_event_revisions"
    __table_args__ = (
        UniqueConstraint("event_series_id", "revision", name="uq_pose_biological_event_revision"),
        CheckConstraint("revision >= 1", name="ck_pose_biological_event_revision"),
        Index("ix_pose_biological_event_current", "event_detection_run_id", "is_current"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    event_series_id: Mapped[str] = mapped_column(String(36), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    supersedes_event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("pose_biological_event_revisions.id", ondelete="SET NULL")
    )
    event_detection_run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pose_event_detection_runs.id", ondelete="CASCADE"), nullable=False
    )
    measurement_series_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pose_measurement_series.id", ondelete="RESTRICT"), nullable=False
    )
    animal_identity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pose_animal_identities.id", ondelete="RESTRICT"), nullable=False
    )
    start_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    peak_frame: Mapped[int | None] = mapped_column(Integer)
    end_frame: Mapped[int | None] = mapped_column(Integer)
    start_time_s: Mapped[float] = mapped_column(Float, nullable=False)
    peak_time_s: Mapped[float | None] = mapped_column(Float)
    end_time_s: Mapped[float | None] = mapped_column(Float)
    baseline_value: Mapped[float | None] = mapped_column(Float)
    peak_value: Mapped[float | None] = mapped_column(Float)
    amplitude: Mapped[float | None] = mapped_column(Float)
    duration_s: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    cycle_state: Mapped[str] = mapped_column(String(30), nullable=False)
    detection_source: Mapped[str] = mapped_column(String(30), nullable=False, default="automated")
    review_state: Mapped[str] = mapped_column(String(30), nullable=False, default="unreviewed")
    rejection_reasons_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    reason: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(100), nullable=False, default="system")
    before_sha256: Mapped[str | None] = mapped_column(String(64))
    after_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
