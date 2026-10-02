"""Canonical immutable pose landmark schema registry."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
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


class PoseLandmarkSchema(Base):
    """Project-scoped identity for an evolving pose landmark schema."""

    __tablename__ = "pose_landmark_schemas"
    __table_args__ = (
        Index("ix_pose_landmark_schemas_project_created", "project_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class PoseLandmarkSchemaRevision(Base):
    """Immutable content revision for a pose landmark schema."""

    __tablename__ = "pose_landmark_schema_revisions"
    __table_args__ = (
        CheckConstraint(
            "revision >= 1",
            name="ck_pose_landmark_schema_revisions_revision",
        ),
        CheckConstraint(
            "keypoint_count >= 1",
            name="ck_pose_landmark_schema_revisions_keypoint_count",
        ),
        UniqueConstraint(
            "schema_id",
            "revision",
            name="uq_pose_landmark_schema_revisions_schema_revision",
        ),
        UniqueConstraint(
            "schema_id",
            "content_hash",
            name="uq_pose_landmark_schema_revisions_schema_hash",
        ),
        Index(
            "ix_pose_landmark_schema_revisions_schema_created",
            "schema_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    schema_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("pose_landmark_schemas.id", ondelete="CASCADE"),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pose-landmarks-0001",
    )
    groups_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    expanded_labels_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    keypoint_count: Mapped[int] = mapped_column(Integer, nullable=False)
    allows_repeated_labels: Mapped[bool] = mapped_column(Boolean, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class PoseModelSchemaBinding(Base):
    """Current immutable schema revision bound to one registered pose model."""

    __tablename__ = "pose_model_schema_bindings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["schema_id", "schema_revision"],
            [
                "pose_landmark_schema_revisions.schema_id",
                "pose_landmark_schema_revisions.revision",
            ],
            ondelete="CASCADE",
        ),
        Index(
            "ix_pose_model_schema_bindings_schema_revision",
            "schema_id",
            "schema_revision",
        ),
    )

    model_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("model_registrations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    schema_id: Mapped[str] = mapped_column(String(36), nullable=False)
    schema_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    bound_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
