"""Model-generated prediction proposals pending review."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
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
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now

if TYPE_CHECKING:
    from reefvision.db.models.image import ImageAsset
    from reefvision.db.models.model_registration import ModelRegistration
    from reefvision.db.models.project import Project


class PredictionProposal(Base):
    """A model output that must be explicitly reviewed before verification."""

    __tablename__ = "prediction_proposals"
    __table_args__ = (
        Index(
            "ix_prediction_proposals_image_status",
            "image_id",
            "review_status",
        ),
        Index(
            "ix_prediction_proposals_job_status",
            "inference_job_id",
            "review_status",
        ),
        Index(
            "ix_prediction_proposals_model_status",
            "model_id",
            "review_status",
        ),
        Index(
            "ix_prediction_proposals_image_geometry_status",
            "image_id",
            "geometry_kind",
            "review_status",
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
    image_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("images.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    model_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("model_registrations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    inference_job_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    model_checksum: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    label_class_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("label_classes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    predicted_label: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    predicted_index: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    geometry_kind: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="bounding_box",
    )
    polygon_json: Mapped[list[list[float]] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    x_min: Mapped[float] = mapped_column(Float, nullable=False)
    y_min: Mapped[float] = mapped_column(Float, nullable=False)
    x_max: Mapped[float] = mapped_column(Float, nullable=False)
    y_max: Mapped[float] = mapped_column(Float, nullable=False)
    review_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="pending",
    )
    was_edited: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    reviewer_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_annotation_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )
    accepted_mask_annotation_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )
    inference_settings_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    provenance_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    project: Mapped[Project] = relationship(back_populates="prediction_proposals")
    image: Mapped[ImageAsset] = relationship(back_populates="prediction_proposals")
    model: Mapped[ModelRegistration] = relationship(back_populates="prediction_proposals")
