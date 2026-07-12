"""Registered local model metadata."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now

if TYPE_CHECKING:
    from reefvision.db.models.prediction_proposal import PredictionProposal
    from reefvision.db.models.project import Project


class ModelRegistration(Base):
    """A project-scoped detection or assist model checkpoint."""

    __tablename__ = "model_registrations"
    __table_args__ = (
        UniqueConstraint("project_id", "sha256", name="uq_model_registrations_project_sha256"),
        UniqueConstraint(
            "project_id", "display_name", name="uq_model_registrations_project_display_name"
        ),
        Index("ix_model_registrations_project_purpose", "project_id", "purpose"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    managed_path: Mapped[str] = mapped_column(String(700), nullable=False, unique=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    framework: Mapped[str] = mapped_column(String(100), nullable=False)
    task: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_version: Mapped[str] = mapped_column(String(100), nullable=False)
    class_map_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    input_size_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    project: Mapped[Project] = relationship(back_populates="models")
    prediction_proposals: Mapped[list[PredictionProposal]] = relationship(
        back_populates="model", cascade="all, delete-orphan"
    )
