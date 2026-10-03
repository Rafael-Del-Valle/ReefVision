"""Persistence for scientist-reviewed pose active-learning acquisition."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


def _uuid() -> str:
    return str(uuid4())


class PoseActiveLearningRound(Base):
    __tablename__ = "pose_active_learning_rounds"
    __table_args__ = (
        CheckConstraint(
            "requested_size >= 1",
            name="ck_pose_al_round_requested_size",
        ),
        CheckConstraint(
            "selected_count >= 1",
            name="ck_pose_al_round_selected_count",
        ),
        CheckConstraint(
            "clip_radius_frames >= 0",
            name="ck_pose_al_round_clip_radius",
        ),
        CheckConstraint(
            "minimum_frame_spacing >= 0",
            name="ck_pose_al_round_spacing",
        ),
        UniqueConstraint(
            "project_id",
            "selection_sha256",
            name="uq_pose_al_round_selection",
        ),
        Index(
            "ix_pose_al_rounds_project_created",
            "project_id",
            "created_at",
        ),
        Index(
            "ix_pose_al_rounds_video_created",
            "video_id",
            "created_at",
        ),
        Index(
            "ix_pose_al_rounds_status",
            "status",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=_uuid,
    )
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    video_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="open",
    )
    selection_unit: Mapped[str] = mapped_column(String(20), nullable=False)
    requested_size: Mapped[int] = mapped_column(Integer, nullable=False)
    selected_count: Mapped[int] = mapped_column(Integer, nullable=False)
    clip_radius_frames: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_frame_spacing: Mapped[int] = mapped_column(Integer, nullable=False)
    model_ids_json: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    scoring_config_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    selection_manifest_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    selection_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    created_by: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="local_user",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class PoseActiveLearningCandidate(Base):
    __tablename__ = "pose_active_learning_candidates"
    __table_args__ = (
        CheckConstraint(
            "focus_frame >= 0",
            name="ck_pose_al_candidate_focus_frame",
        ),
        CheckConstraint(
            "frame_start >= 0",
            name="ck_pose_al_candidate_start_frame",
        ),
        CheckConstraint(
            "frame_end >= frame_start",
            name="ck_pose_al_candidate_frame_order",
        ),
        CheckConstraint(
            "focus_frame >= frame_start AND focus_frame <= frame_end",
            name="ck_pose_al_candidate_focus_in_window",
        ),
        CheckConstraint(
            "acquisition_score >= 0 AND acquisition_score <= 1",
            name="ck_pose_al_candidate_score",
        ),
        CheckConstraint(
            "pose_schema_revision >= 1",
            name="ck_pose_al_candidate_schema_revision",
        ),
        CheckConstraint(
            "source_track_revision >= 1",
            name="ck_pose_al_candidate_track_revision",
        ),
        UniqueConstraint(
            "round_id",
            "video_track_id",
            "focus_frame",
            name="uq_pose_al_candidate_round_track_frame",
        ),
        Index(
            "ix_pose_al_candidates_round_score",
            "round_id",
            "acquisition_score",
        ),
        Index(
            "ix_pose_al_candidates_track_frame",
            "video_track_id",
            "focus_frame",
        ),
        Index(
            "ix_pose_al_candidates_review",
            "review_status",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=_uuid,
    )
    round_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "pose_active_learning_rounds.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    video_track_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("video_tracks.id", ondelete="CASCADE"),
        nullable=False,
    )
    focus_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    frame_start: Mapped[int] = mapped_column(Integer, nullable=False)
    frame_end: Mapped[int] = mapped_column(Integer, nullable=False)
    acquisition_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )
    score_components_json: Mapped[dict[str, float]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    reason_codes_json: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    pose_schema_id: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    pose_schema_revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    source_track_revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    source_model_ids_json: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    source_job_ids_json: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    provenance_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    provenance_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    review_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="pending",
    )
    review_started_track_revision: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    verified_track_revision: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    verified_pose_sha256: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    correction_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "pose_landmark_corrections.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    reviewed_by: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
