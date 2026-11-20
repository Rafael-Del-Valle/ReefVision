"""Local source configuration and immutable capture receipts."""

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class AcquisitionSource(Base):
    __tablename__ = "acquisition_sources"
    __table_args__ = (
        Index("ix_acquisition_sources_project", "project_id", "created_at", "id"),
        CheckConstraint("cursor >= 0 AND revision >= 1", name="ck_acquisition_source_cursor"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))
    label: Mapped[str] = mapped_column(String(200))
    configuration_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    source_sha256: Mapped[str] = mapped_column(String(64))
    cursor: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(32))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    last_error: Mapped[str | None] = mapped_column(Text)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    local_consent_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class AcquisitionCapture(Base):
    __tablename__ = "acquisition_captures"
    __table_args__ = (
        UniqueConstraint("source_id", "capture_key", name="uq_acquisition_capture_request"),
        UniqueConstraint("source_id", "ordinal", name="uq_acquisition_capture_ordinal"),
        Index("ix_acquisition_captures_project", "project_id", "created_at", "id"),
        CheckConstraint("ordinal >= 0", name="ck_acquisition_capture_ordinal"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    source_id: Mapped[str] = mapped_column(ForeignKey("acquisition_sources.id", ondelete="CASCADE"))
    capture_key: Mapped[str] = mapped_column(String(200))
    ordinal: Mapped[int] = mapped_column(Integer)
    field_batch_id: Mapped[str] = mapped_column(
        ForeignKey("field_capture_batches.id", ondelete="RESTRICT")
    )
    field_observation_id: Mapped[str] = mapped_column(
        ForeignKey("field_capture_observations.id", ondelete="RESTRICT")
    )
    content_sha256: Mapped[str] = mapped_column(String(64))
    receipt_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
