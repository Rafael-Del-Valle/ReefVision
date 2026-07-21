"""Persisted image embedding used for active-learning diversity selection."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class ImageEmbedding(Base):
    __tablename__ = "image_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "image_id",
            "embedding_key",
            name="uq_image_embeddings_image_key",
        ),
        Index(
            "ix_image_embeddings_project_model",
            "project_id",
            "embedding_model_id",
        ),
        Index("ix_image_embeddings_vector_sha256", "vector_sha256"),
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
    embedding_model_id: Mapped[str] = mapped_column(String(300), nullable=False)
    embedding_model_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    embedding_key: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(100), nullable=False, default="legacy")
    model_version: Mapped[str] = mapped_column(String(100), nullable=False, default="unknown")
    preprocessing_version: Mapped[str] = mapped_column(
        String(100), nullable=False, default="legacy"
    )
    source_image_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_kind: Mapped[str] = mapped_column(String(30), nullable=False, default="image")
    crop_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    normalization: Mapped[str] = mapped_column(String(40), nullable=False, default="l2")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ready")
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    vector_json: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    vector_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )
