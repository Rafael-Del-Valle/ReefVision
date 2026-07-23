"""Independent reviewed classification assigned to an image or annotation target."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class ClassificationAssignment(Base):
    """A reviewed label that does not overwrite the target's primary detection class."""

    __tablename__ = "classification_assignments"
    __table_args__ = (
        Index(
            "ix_classification_assignments_target_set_status",
            "target_key",
            "label_set_id",
            "status",
        ),
        Index(
            "ix_classification_assignments_project_model_created",
            "project_id",
            "source_model_id",
            "created_at",
        ),
        Index(
            "ix_classification_assignments_image_set",
            "image_id",
            "label_set_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label_set_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("classification_label_sets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    target_key: Mapped[str] = mapped_column(String(500), nullable=False)
    image_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("images.id", ondelete="CASCADE"), nullable=False, index=True
    )
    annotation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("annotations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    mask_annotation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("mask_annotations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    fragment_key: Mapped[str | None] = mapped_column(String(300), nullable=True, index=True)
    label_class_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("label_classes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="accepted_prediction"
    )
    source_model_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("model_registrations.id", ondelete="SET NULL"), nullable=True
    )
    source_prediction_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("classification_predictions.id", ondelete="SET NULL"), nullable=True
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    probabilities_json: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="accepted")
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
