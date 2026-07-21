"""Append-only software acceptance results for real provider executions."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class ProviderAcceptanceRecord(Base):
    """A load/infer/unload observation, never a scientific accuracy claim."""

    __tablename__ = "provider_acceptance_records"
    __table_args__ = (
        Index("ix_provider_acceptance_provider_model", "provider_id", "model_id"),
        Index("ix_provider_acceptance_recorded", "recorded_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    provider_asset_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("provider_model_assets.id", ondelete="SET NULL"),
        nullable=True,
    )
    provider_id: Mapped[str] = mapped_column(String(100), nullable=False)
    model_id: Mapped[str] = mapped_column(String(300), nullable=False)
    checkpoint_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    device: Mapped[str] = mapped_column(String(80), nullable=False)
    runtime_versions_json: Mapped[dict[str, str]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    load_result: Mapped[str] = mapped_column(String(30), nullable=False)
    inference_result: Mapped[str] = mapped_column(String(30), nullable=False)
    unload_result: Mapped[str] = mapped_column(String(30), nullable=False)
    peak_memory_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    execution_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    warnings_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    test_input_identifier: Mapped[str] = mapped_column(String(500), nullable=False)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    validation_kind: Mapped[str] = mapped_column(
        String(80), nullable=False, default="software_acceptance"
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
