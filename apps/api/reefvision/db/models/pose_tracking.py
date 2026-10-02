"""Canonical temporal pose-tracking persistence models."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
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


class PoseLandmarkTrack(Base):
    """Persistent temporal identity for one semantic landmark tracklet."""

    __tablename__ = "pose_landmark_tracks"
    __table_args__ = (
        Index(
            "ix_pose_landmark_tracks_parent_label",
            "parent_video_track_id",
            "semantic_label",
        ),
        Index(
            "ix_pose_landmark_tracks_parent_frames",
            "parent_video_track_id",
            "first_frame",
            "last_frame",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    parent_video_track_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("video_tracks.id", ondelete="CASCADE"),
        nullable=False,
    )
    pose_schema_id: Mapped[str] = mapped_column(String(200), nullable=False)
    pose_schema_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    semantic_label: Mapped[str] = mapped_column(String(100), nullable=False)
    lifecycle_state: Mapped[str] = mapped_column(String(20), nullable=False, default="tentative")
    first_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    last_frame: Mapped[int | None] = mapped_column(Integer, nullable=True)
    origin: Mapped[str] = mapped_column(String(20), nullable=False, default="tracker")
    source_model_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("model_registrations.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_job_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    association_algorithm: Mapped[str | None] = mapped_column(String(100), nullable=True)
    association_algorithm_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    association_parameters_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    association_parameters_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    terminated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PoseLandmarkObservation(Base):
    """Immutable frame-level observation revision."""

    __tablename__ = "pose_landmark_observations"
    __table_args__ = (
        UniqueConstraint(
            "observation_series_id",
            "revision",
            name="uq_pose_landmark_observations_series_revision",
        ),
        Index(
            "ix_pose_landmark_observations_parent_frame",
            "parent_video_track_id",
            "frame_index",
        ),
        Index(
            "ix_pose_landmark_observations_parent_label_frame",
            "parent_video_track_id",
            "semantic_label",
            "frame_index",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    observation_series_id: Mapped[str] = mapped_column(String(36), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    supersedes_observation_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("pose_landmark_observations.id", ondelete="SET NULL"),
        nullable=True,
    )
    parent_video_track_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("video_tracks.id", ondelete="CASCADE"),
        nullable=False,
    )
    frame_index: Mapped[int] = mapped_column(Integer, nullable=False)
    time_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    pose_schema_id: Mapped[str] = mapped_column(String(200), nullable=False)
    pose_schema_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    semantic_label: Mapped[str] = mapped_column(String(100), nullable=False)
    occurrence_index: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_x_px: Mapped[float | None] = mapped_column(Float, nullable=True)
    observed_y_px: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_x_px: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_y_px: Mapped[float | None] = mapped_column(Float, nullable=True)
    landmark_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    visibility_state: Mapped[str] = mapped_column(String(30), nullable=False)
    observation_source: Mapped[str] = mapped_column(String(20), nullable=False)
    source_model_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("model_registrations.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_job_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class PoseLandmarkAssociationDecision(Base):
    """Immutable temporal-identity decision for one observation revision."""

    __tablename__ = "pose_landmark_association_decisions"
    __table_args__ = (
        UniqueConstraint(
            "observation_id",
            "decision_revision",
            name="uq_pose_landmark_associations_observation_revision",
        ),
        Index(
            "ix_pose_landmark_associations_track",
            "selected_landmark_track_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    observation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("pose_landmark_observations.id", ondelete="CASCADE"),
        nullable=False,
    )
    decision_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    supersedes_decision_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("pose_landmark_association_decisions.id", ondelete="SET NULL"),
        nullable=True,
    )
    selected_landmark_track_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("pose_landmark_tracks.id", ondelete="SET NULL"),
        nullable=True,
    )
    previous_observation_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("pose_landmark_observations.id", ondelete="SET NULL"),
        nullable=True,
    )
    association_state: Mapped[str] = mapped_column(String(30), nullable=False)
    association_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    verification_state: Mapped[str] = mapped_column(
        String(30), nullable=False, default="unreviewed"
    )
    association_source: Mapped[str] = mapped_column(String(20), nullable=False)
    candidate_margin: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_breakdown_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    algorithm: Mapped[str | None] = mapped_column(String(100), nullable=True)
    algorithm_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    parameters_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class PoseLandmarkAssociationCandidate(Base):
    """Ranked alternative identity candidate retained for audit."""

    __tablename__ = "pose_landmark_association_candidates"
    __table_args__ = (
        UniqueConstraint(
            "association_decision_id",
            "rank",
            name="uq_pose_landmark_candidates_decision_rank",
        ),
        Index(
            "ix_pose_landmark_candidates_decision",
            "association_decision_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    association_decision_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("pose_landmark_association_decisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    candidate_landmark_track_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("pose_landmark_tracks.id", ondelete="CASCADE"),
        nullable=False,
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    total_cost: Mapped[float] = mapped_column(Float, nullable=False)
    normalized_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    motion_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    geometry_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    appearance_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    ordering_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    shape_cost: Mapped[float | None] = mapped_column(Float, nullable=True)


class PoseLandmarkCorrection(Base):
    """Append-only human correction audit event."""

    __tablename__ = "pose_landmark_corrections"
    __table_args__ = (
        Index(
            "ix_pose_landmark_corrections_parent_created",
            "parent_video_track_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    parent_video_track_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("video_tracks.id", ondelete="CASCADE"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    target_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[str] = mapped_column(String(100), nullable=False)
    frame_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frame_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    before_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    after_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    actor: Mapped[str] = mapped_column(String(100), nullable=False, default="local_user")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class PoseLandmarkIdentityBreak(Base):
    """Explicit boundary where temporal biological identity is no longer asserted."""

    __tablename__ = "pose_landmark_identity_breaks"
    __table_args__ = (
        Index(
            "ix_pose_landmark_identity_breaks_parent_frame",
            "parent_video_track_id",
            "break_after_frame",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    parent_video_track_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("video_tracks.id", ondelete="CASCADE"),
        nullable=False,
    )
    predecessor_landmark_track_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("pose_landmark_tracks.id", ondelete="CASCADE"),
        nullable=False,
    )
    successor_landmark_track_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("pose_landmark_tracks.id", ondelete="SET NULL"),
        nullable=True,
    )
    break_after_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    successor_start_frame: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(String(50), nullable=False)
    decision_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    human_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    correction_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("pose_landmark_corrections.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
