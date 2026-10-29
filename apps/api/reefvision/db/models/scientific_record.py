"""Additive scientific records and small offline provider datasets."""

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class ScientificRecord(Base):
    __tablename__ = "scientific_records"
    __table_args__ = (
        Index("ix_scientific_project_variable_time", "project_id", "variable", "observed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    variable: Mapped[str] = mapped_column(String(100))
    source_kind: Mapped[str] = mapped_column(String(30))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    image_id: Mapped[str | None] = mapped_column(ForeignKey("images.id", ondelete="RESTRICT"))
    video_id: Mapped[str | None] = mapped_column(ForeignKey("videos.id", ondelete="RESTRICT"))
    track_id: Mapped[str | None] = mapped_column(ForeignKey("video_tracks.id", ondelete="RESTRICT"))
    model_run_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="RESTRICT"))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    content_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class EnvironmentalCacheEntry(Base):
    __tablename__ = "environmental_cache_entries"
    __table_args__ = (
        UniqueConstraint("project_id", "cache_key", name="uq_environmental_cache_project_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    cache_key: Mapped[str] = mapped_column(String(64))
    source_url: Mapped[str] = mapped_column(String(2000))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    content_sha256: Mapped[str] = mapped_column(String(64))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class EnvironmentalEventDefinition(Base):
    """Immutable researcher-authored query, independent of changing source observations."""

    __tablename__ = "environmental_event_definitions"
    __table_args__ = (
        Index("ix_environmental_event_definition_project", "project_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    query_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    definition_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
