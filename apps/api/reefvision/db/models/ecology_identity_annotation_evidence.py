"""Append-only, unverified links from organism image evidence to annotation revisions."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class EcologyIdentityAnnotationEvidence(Base):
    """Freeze an annotation revision claim; never confer scientific verification."""

    __tablename__ = "ecology_identity_annotation_evidence"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "annotation_kind",
            "annotation_id",
            name="uq_ecology_identity_annotation_evidence",
        ),
        Index(
            "ix_ecology_annotation_evidence_project_image",
            "project_id",
            "image_evidence_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    image_evidence_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ecology_identity_image_evidence.id", ondelete="RESTRICT"),
        nullable=False,
    )
    annotation_kind: Mapped[str] = mapped_column(String(10), nullable=False)
    annotation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    annotation_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    annotation_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
