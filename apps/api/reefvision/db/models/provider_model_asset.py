"""Restart-safe registrations for managed and trusted external model assets."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class ProviderModelAsset(Base):
    """One provider/checkpoint pairing independent of any project registration."""

    __tablename__ = "provider_model_assets"
    __table_args__ = (
        UniqueConstraint("model_id", name="uq_provider_model_assets_model_id"),
        Index("ix_provider_model_assets_provider_state", "provider_id", "state"),
        Index("ix_provider_model_assets_checksum", "checkpoint_sha256"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    provider_id: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_version: Mapped[str] = mapped_column(String(100), nullable=False)
    model_id: Mapped[str] = mapped_column(String(300), nullable=False)
    architecture: Mapped[str] = mapped_column(String(200), nullable=False)
    task: Mapped[str] = mapped_column(String(100), nullable=False)
    capabilities_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    checkpoint_path: Mapped[str] = mapped_column(String(1200), nullable=False)
    checkpoint_path_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    checkpoint_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    checkpoint_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    checkpoint_format: Mapped[str] = mapped_column(String(80), nullable=False)
    file_manifest_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    source: Mapped[str] = mapped_column(String(500), nullable=False)
    revision: Mapped[str | None] = mapped_column(String(200), nullable=True)
    license_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    required_packages_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    optional_packages_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    supported_devices_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    preferred_device: Mapped[str] = mapped_column(String(30), nullable=False, default="auto")
    estimated_vram_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    input_types_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    output_types_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    prompt_types_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    supports_training: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    supports_inference: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    supports_video: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="unavailable")
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    last_health_check_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    last_health_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_successful_load_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_successful_inference_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
