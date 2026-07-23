"""Structured classification task and label-set definition."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class ClassificationLabelSet(Base):
    """A named classification task that can coexist with an object's primary class."""

    __tablename__ = "classification_label_sets"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "key",
            name="uq_classification_label_sets_project_key",
        ),
        Index(
            "ix_classification_label_sets_project_target",
            "project_id",
            "target_kind",
            "is_active",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_kind: Mapped[str] = mapped_column(String(30), nullable=False, default="annotation")
    cardinality: Mapped[str] = mapped_column(String(20), nullable=False, default="single")
    allowed_class_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    replaces_primary_class: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
