"""Immutable scientist-verified pose training datasets."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
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


class PoseTrainingDataset(Base):
    """Immutable snapshot derived from one completed pose AL round."""

    __tablename__ = "pose_training_datasets"
    __table_args__ = (
        CheckConstraint(
            "pose_schema_revision >= 1",
            name="ck_pose_training_dataset_schema_revision",
        ),
        CheckConstraint(
            "item_count >= 1",
            name="ck_pose_training_dataset_item_count",
        ),
        UniqueConstraint(
            "source_round_id",
            name="uq_pose_training_dataset_source_round",
        ),
        UniqueConstraint(
            "project_id",
            "manifest_sha256",
            name="uq_pose_training_dataset_manifest",
        ),
        Index(
            "ix_pose_training_datasets_project_created",
            "project_id",
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
        ForeignKey(
            "projects.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    source_round_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="complete",
    )
    schema_version: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pose-training-dataset-0001",
    )
    pose_schema_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )
    pose_schema_revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    pose_schema_content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    source_selection_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    source_retraining_manifest_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    manifest_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    manifest_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    item_count: Mapped[int] = mapped_column(
        Integer,
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


class PoseTrainingDatasetItem(Base):
    """Frozen canonical pose truth for one scientist-verified frame."""

    __tablename__ = "pose_training_dataset_items"
    __table_args__ = (
        CheckConstraint(
            "frame_index >= 0",
            name="ck_pose_training_item_frame",
        ),
        CheckConstraint(
            "video_revision >= 1",
            name="ck_pose_training_item_video_revision",
        ),
        CheckConstraint(
            "verified_track_revision >= 1",
            name="ck_pose_training_item_track_revision",
        ),
        CheckConstraint(
            "pose_schema_revision >= 1",
            name="ck_pose_training_item_schema_revision",
        ),
        UniqueConstraint(
            "dataset_id",
            "candidate_id",
            name="uq_pose_training_item_candidate",
        ),
        UniqueConstraint(
            "dataset_id",
            "video_track_id",
            "frame_index",
            name="uq_pose_training_item_track_frame",
        ),
        Index(
            "ix_pose_training_items_dataset_frame",
            "dataset_id",
            "frame_index",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=_uuid,
    )
    dataset_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "pose_training_datasets.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    candidate_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )
    video_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )
    video_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    video_revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    video_track_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )
    label_class_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )
    frame_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    verified_track_revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    pose_schema_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )
    pose_schema_revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    pose_schema_content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    verified_pose_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    canonical_pose_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    source_models_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    source_job_ids_json: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    acquisition_provenance_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    review_provenance_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    item_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
