"""Project-default class visibility preferences by layer."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class ProjectClassVisibilityDefault(Base):
    """A persisted project-wide class visibility default."""

    __tablename__ = "project_class_visibility_defaults"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "layer_type",
            name="uq_project_class_visibility_defaults_scope",
        ),
        Index(
            "ix_project_class_visibility_defaults_project",
            "project_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    layer_type: Mapped[str] = mapped_column(String(50), nullable=False)
    hidden_class_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    updated_by_identity: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
