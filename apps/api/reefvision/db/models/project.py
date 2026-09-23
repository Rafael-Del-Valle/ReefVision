"""Project database model."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from reefvision.db.base import Base

if TYPE_CHECKING:
    from reefvision.db.models.dataset_version import DatasetVersion
    from reefvision.db.models.export_record import ExportRecord
    from reefvision.db.models.image import ImageAsset
    from reefvision.db.models.label_class import LabelClass
    from reefvision.db.models.model_registration import ModelRegistration
    from reefvision.db.models.prediction_proposal import PredictionProposal


def utc_now() -> datetime:
    return datetime.now(UTC)


class Project(Base):
    """A locally managed ReefVision research project."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(220), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_root: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    default_annotation_type: Mapped[str] = mapped_column(String(30), default="bbox", nullable=False)
    georeference_height_offset_m: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    georeference_height_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    label_classes: Mapped[list[LabelClass]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="LabelClass.display_order"
    )
    images: Mapped[list[ImageAsset]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    models: Mapped[list[ModelRegistration]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    prediction_proposals: Mapped[list[PredictionProposal]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    dataset_versions: Mapped[list[DatasetVersion]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    exports: Mapped[list[ExportRecord]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
