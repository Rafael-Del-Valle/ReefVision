"""Append-only, project-scoped ecological organism identity revisions."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class EcologyIdentityRevision(Base):
    """Registered biological identity metadata, not verified observation truth."""

    __tablename__ = "ecology_identity_revisions"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "organism_key",
            "revision",
            name="uq_ecology_identity_project_key_revision",
        ),
        Index(
            "ix_ecology_identity_project_key",
            "project_id",
            "organism_key",
            "revision",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    organism_key: Mapped[str] = mapped_column(String(100), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    parent_colony_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    experimental_unit_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    experimental_unit_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
