"""Behavior-classifier persistence models."""

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
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class BehaviorClassifierModel(Base):
    __tablename__ = "behavior_classifier_models"
    __table_args__ = (
        CheckConstraint(
            "training_sample_count >= 1",
            name="ck_behavior_classifier_training_samples",
        ),
        UniqueConstraint(
            "project_id",
            "display_name",
            name="uq_behavior_classifier_project_name",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ethogram_revision_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("behavior_ethogram_revisions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    channel: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(100), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(100), nullable=False)
    feature_set_version: Mapped[str] = mapped_column(String(100), nullable=False)
    feature_preset: Mapped[str] = mapped_column(String(100), nullable=False)
    feature_names_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    feature_request_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    scaler_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    centroids_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    class_counts_json: Mapped[dict[str, int]] = mapped_column(JSON, nullable=False, default=dict)
    training_track_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    training_bout_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    training_sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    training_manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False, default="local_user")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class BehaviorPrediction(Base):
    __tablename__ = "behavior_predictions"
    __table_args__ = (
        CheckConstraint("start_frame >= 0", name="ck_behavior_prediction_start"),
        CheckConstraint(
            "end_frame >= start_frame",
            name="ck_behavior_prediction_frame_order",
        ),
        CheckConstraint(
            "prediction_score >= 0 AND prediction_score <= 1",
            name="ck_behavior_prediction_score",
        ),
        CheckConstraint(
            "source_track_revision >= 1",
            name="ck_behavior_prediction_track_revision",
        ),
        UniqueConstraint(
            "video_track_id",
            "classifier_id",
            "source_track_revision",
            "start_frame",
            "end_frame",
            name="uq_behavior_prediction_window",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    video_track_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("video_tracks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    classifier_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("behavior_classifier_models.id", ondelete="CASCADE"),
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
    channel: Mapped[str] = mapped_column(String(100), nullable=False)
    start_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    end_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    prediction_score: Mapped[float] = mapped_column(Float, nullable=False)
    scores_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    feature_vector_json: Mapped[dict[str, float]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    feature_parameters_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_track_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    review_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="pending",
    )
    accepted_bout_series_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
