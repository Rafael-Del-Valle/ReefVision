"""Immutable audio, explicit clock anchors, and append-only attributed review."""

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class BioacousticAsset(Base):
    __tablename__ = "bioacoustic_assets"
    __table_args__ = (
        UniqueConstraint("project_id", "sha256", name="uq_audio_original"),
        Index("ix_audio_assets_project", "project_id", "created_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    original_asset_id: Mapped[str] = mapped_column(String(36))
    original_project_id: Mapped[str] = mapped_column(String(36))
    original_filename: Mapped[str] = mapped_column(String(255))
    managed_path: Mapped[str] = mapped_column(String(700))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sample_rate_hz: Mapped[int] = mapped_column(Integer)
    sample_count: Mapped[int] = mapped_column(Integer)
    channel_count: Mapped[int] = mapped_column(Integer)
    bits_per_sample: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class BioacousticClockAnchor(Base):
    __tablename__ = "bioacoustic_clock_anchors"
    __table_args__ = (
        UniqueConstraint("asset_id", "anchor_sha256", name="uq_audio_anchor_content"),
        Index("ix_audio_anchors_owner", "project_id", "asset_id", "created_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    asset_id: Mapped[str] = mapped_column(ForeignKey("bioacoustic_assets.id", ondelete="CASCADE"))
    anchor_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    anchor_sha256: Mapped[str] = mapped_column(String(64))
    author: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class BioacousticProposal(Base):
    __tablename__ = "bioacoustic_proposals"
    __table_args__ = (
        Index("ix_audio_proposals_owner", "project_id", "asset_id", "created_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    asset_id: Mapped[str] = mapped_column(ForeignKey("bioacoustic_assets.id", ondelete="CASCADE"))
    proposal_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    proposal_sha256: Mapped[str] = mapped_column(String(64))
    author: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class BioacousticReview(Base):
    __tablename__ = "bioacoustic_reviews"
    __table_args__ = (
        UniqueConstraint("proposal_id", "revision", name="uq_audio_review_revision"),
        Index("ix_audio_reviews_owner", "project_id", "proposal_id", "revision"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    proposal_id: Mapped[str] = mapped_column(
        ForeignKey("bioacoustic_proposals.id", ondelete="CASCADE")
    )
    reviewer: Mapped[str] = mapped_column(String(200))
    decision: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class BioacousticReport(Base):
    __tablename__ = "bioacoustic_reports"
    __table_args__ = (
        UniqueConstraint("asset_id", "report_sha256", name="uq_audio_report_content"),
        Index("ix_audio_reports_owner", "project_id", "asset_id", "created_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    asset_id: Mapped[str] = mapped_column(ForeignKey("bioacoustic_assets.id", ondelete="CASCADE"))
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    report_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
