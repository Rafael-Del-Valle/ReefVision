"""Project-scoped append-only links from organism identities to source images."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class EcologyIdentityImageEvidence(Base):
    """A source-image association, not a reviewed biological observation."""

    __tablename__ = "ecology_identity_image_evidence"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "organism_key",
            "image_id",
            name="uq_ecology_identity_image_evidence",
        ),
        Index(
            "ix_ecology_image_evidence_project_organism",
            "project_id",
            "organism_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    organism_key: Mapped[str] = mapped_column(String(100), nullable=False)
    identity_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    image_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("images.id", ondelete="RESTRICT"), nullable=False
    )
    image_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # NULL marks pre-migration links whose capture/geometry metadata was not frozen.
    source_metadata_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    @property
    def source_metadata_evidence_status(self) -> str:
        return "frozen" if self.source_metadata_sha256 is not None else "legacy_unfrozen"
