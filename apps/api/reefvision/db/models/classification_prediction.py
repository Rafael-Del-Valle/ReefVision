"""Reviewable classification prediction for an image, box, mask, or fragment."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class ClassificationPrediction(Base):
    __tablename__ = "classification_predictions"
    __table_args__ = (
        Index(
            "ix_classification_predictions_image_status",
            "image_id",
            "review_status",
        ),
        Index(
            "ix_classification_predictions_model_created",
            "model_id",
            "created_at",
        ),
        Index(
            "ix_classification_predictions_target_status",
            "target_kind",
            "target_key",
            "review_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    image_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("images.id", ondelete="CASCADE"), nullable=False, index=True
    )
    annotation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("annotations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    mask_annotation_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("mask_annotations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    target_kind: Mapped[str] = mapped_column(String(30), nullable=False, default="annotation")
    target_key: Mapped[str] = mapped_column(String(500), nullable=False)
    fragment_key: Mapped[str | None] = mapped_column(String(300), nullable=True, index=True)
    model_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("model_registrations.id", ondelete="RESTRICT"), nullable=False
    )
    inference_job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    label_set: Mapped[str] = mapped_column(String(100), nullable=False, default="default")
    classification_mode: Mapped[str] = mapped_column(String(40), nullable=False)
    x_min: Mapped[float] = mapped_column(Float, nullable=False)
    y_min: Mapped[float] = mapped_column(Float, nullable=False)
    x_max: Mapped[float] = mapped_column(Float, nullable=False)
    y_max: Mapped[float] = mapped_column(Float, nullable=False)
    predicted_label: Mapped[str] = mapped_column(String(300), nullable=False)
    predicted_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    label_class_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("label_classes.id", ondelete="SET NULL"), nullable=True
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    probabilities_json: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False, default=dict)
    review_status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    accepted_label_class_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("label_classes.id", ondelete="SET NULL"), nullable=True
    )
    inference_settings_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
