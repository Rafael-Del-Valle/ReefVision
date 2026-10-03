"""Revisioned behavior ethograms and track-level behavior bouts."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class BehaviorEthogramRevision(Base):
    __tablename__ = "behavior_ethogram_revisions"
    __table_args__ = (
        CheckConstraint("revision >= 1", name="ck_behavior_ethogram_revision"),
        UniqueConstraint(
            "ethogram_series_id",
            "revision",
            name="uq_behavior_ethogram_series_revision",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    ethogram_series_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    supersedes_revision_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("behavior_ethogram_revisions.id", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    definition_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False, default="local_user")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )


class BehaviorStateDefinition(Base):
    __tablename__ = "behavior_state_definitions"
    __table_args__ = (
        CheckConstraint("sort_order >= 0", name="ck_behavior_state_sort_order"),
        UniqueConstraint(
            "ethogram_revision_id",
            "code",
            name="uq_behavior_state_ethogram_code",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    ethogram_revision_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("behavior_ethogram_revisions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    channel: Mapped[str] = mapped_column(String(100), nullable=False, default="primary")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class BehaviorBoutRevision(Base):
    __tablename__ = "behavior_bout_revisions"
    __table_args__ = (
        CheckConstraint("revision >= 1", name="ck_behavior_bout_revision"),
        CheckConstraint("start_frame >= 0", name="ck_behavior_bout_start_frame"),
        CheckConstraint("end_frame >= start_frame", name="ck_behavior_bout_frame_order"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_behavior_bout_confidence",
        ),
        CheckConstraint("source_track_revision >= 1", name="ck_behavior_bout_track_revision"),
        UniqueConstraint(
            "bout_series_id",
            "revision",
            name="uq_behavior_bout_series_revision",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    bout_series_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    supersedes_bout_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("behavior_bout_revisions.id", ondelete="SET NULL"),
        nullable=True,
    )
    video_track_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("video_tracks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ethogram_revision_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("behavior_ethogram_revisions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    behavior_state_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("behavior_state_definitions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    start_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    end_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_status: Mapped[str] = mapped_column(String(30), nullable=False)
    source_track_revision: Mapped[int] = mapped_column(Integer, nullable=False)
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
    source_behavior_classifier_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("behavior_classifier_models.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_behavior_prediction_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("behavior_predictions.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    revision_reason: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="manual_annotation",
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False, default="local_user")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
