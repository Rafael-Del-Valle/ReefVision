"""Immutable taxonomy decisions and repeated observation evidence."""

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class TaxonomyRecord:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class TaxonProposal(TaxonomyRecord, Base):
    __tablename__ = "taxonomy_proposals"
    __table_args__ = (Index("ix_taxonomy_proposals_project", "project_id", "created_at", "id"),)

    identity_revision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ecology_identity_revisions.id"), nullable=False
    )
    author_role_revision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reviewer_lab_role_revisions.id"), nullable=False
    )


class TaxonReview(TaxonomyRecord, Base):
    __tablename__ = "taxonomy_reviews"
    __table_args__ = (
        UniqueConstraint("proposal_id", "revision", name="uq_taxonomy_review_revision"),
    )

    proposal_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("taxonomy_proposals.id", ondelete="CASCADE"), nullable=False
    )
    reviewer_role_revision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reviewer_lab_role_revisions.id"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)


class DetectabilityVisit(TaxonomyRecord, Base):
    __tablename__ = "detectability_visits"
    __table_args__ = (
        Index("ix_detectability_visits_project_start", "project_id", "started_at", "id"),
        UniqueConstraint(
            "project_id", "organism_key", "protocol", "started_at", name="uq_detectability_visit"
        ),
    )

    proposal_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("taxonomy_proposals.id"), nullable=False
    )
    observer_role_revision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reviewer_lab_role_revisions.id"), nullable=False
    )
    organism_key: Mapped[str] = mapped_column(String(100), nullable=False)
    protocol: Mapped[str] = mapped_column(String(200), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DetectabilityPresenceReview(TaxonomyRecord, Base):
    __tablename__ = "detectability_presence_reviews"
    __table_args__ = (
        UniqueConstraint("visit_id", "revision", name="uq_detectability_presence_revision"),
    )

    visit_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("detectability_visits.id", ondelete="CASCADE"), nullable=False
    )
    reviewer_role_revision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reviewer_lab_role_revisions.id"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)


class DetectabilityAssessment(TaxonomyRecord, Base):
    __tablename__ = "detectability_assessments"
    __table_args__ = (
        Index("ix_detectability_assessments_project", "project_id", "created_at", "id"),
        UniqueConstraint("project_id", "content_sha256", name="uq_detectability_result_content"),
    )
