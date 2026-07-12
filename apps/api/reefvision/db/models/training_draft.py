"""Persistent draft configuration for the Training workspace."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class TrainingDraft(Base):
    """A saved but not yet launched training configuration."""

    __tablename__ = "training_drafts"
    __table_args__ = (
        Index("ix_training_drafts_project_updated", "project_id", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    run_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    dataset_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("dataset_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    dataset_manifest_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    split_manifest_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    task: Mapped[str | None] = mapped_column(String(40), nullable=True)
    catalog_model_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    provider_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    architecture: Mapped[str | None] = mapped_column(String(200), nullable=True)
    initial_checkpoint_source: Mapped[str] = mapped_column(
        String(30), nullable=False, default="scratch"
    )
    initial_checkpoint_model_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("model_registrations.id", ondelete="SET NULL"), nullable=True
    )
    resolved_model_asset_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_model_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parameter_registry_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    selected_preset: Mapped[str | None] = mapped_column(String(200), nullable=True)
    installation_state: Mapped[str | None] = mapped_column(String(40), nullable=True)
    device: Mapped[str] = mapped_column(String(60), nullable=False, default="auto")
    precision: Mapped[str] = mapped_column(String(30), nullable=False, default="fp32")
    random_seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tiling_config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    training_config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    tuning_config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    evaluation_config_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    resource_limits_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    validation_state_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
