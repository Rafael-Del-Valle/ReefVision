"""Local Reviewer Lab records. Credentials are separate from exportable provenance."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class ReviewerLabMember(Base):
    __tablename__ = "reviewer_lab_members"
    __table_args__ = (
        UniqueConstraint("project_id", "name_key", name="uq_reviewer_lab_member_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    name_key: Mapped[str] = mapped_column(String(250))
    role: Mapped[str] = mapped_column(String(16))


class ReviewerLabRoleRevision(Base):
    __tablename__ = "reviewer_lab_role_revisions"
    __table_args__ = (
        UniqueConstraint("member_id", "revision", name="uq_reviewer_lab_role_revision"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    member_id: Mapped[str] = mapped_column(
        ForeignKey("reviewer_lab_members.id", ondelete="CASCADE")
    )
    revision: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean)
    previous_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("reviewer_lab_role_revisions.id"), unique=True
    )
    granted_by_role_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("reviewer_lab_role_revisions.id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ReviewerLabCredential(Base):
    __tablename__ = "reviewer_lab_credentials"

    role_revision_id: Mapped[str] = mapped_column(
        ForeignKey("reviewer_lab_role_revisions.id", ondelete="CASCADE"), primary_key=True
    )
    credential_sha256: Mapped[str] = mapped_column(String(64), unique=True)


class ReviewerLabRoundRecord(Base):
    __tablename__ = "reviewer_lab_rounds"
    __table_args__ = (
        UniqueConstraint("project_id", "operation_id", name="uq_reviewer_lab_round_operation"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    operation_id: Mapped[str] = mapped_column(String(36))
    request_sha256: Mapped[str] = mapped_column(String(64))
    plan_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    plan_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ReviewerLabDecisionRecord(Base):
    __tablename__ = "reviewer_lab_decisions"
    __table_args__ = (
        UniqueConstraint("round_id", "subject_id", "slot", name="uq_reviewer_lab_decision_slot"),
        UniqueConstraint("round_id", "operation_id", name="uq_reviewer_lab_decision_operation"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    round_id: Mapped[str] = mapped_column(ForeignKey("reviewer_lab_rounds.id", ondelete="CASCADE"))
    subject_id: Mapped[str] = mapped_column(String(36))
    role_revision_id: Mapped[str] = mapped_column(ForeignKey("reviewer_lab_role_revisions.id"))
    operation_id: Mapped[str] = mapped_column(String(36))
    request_sha256: Mapped[str] = mapped_column(String(64))
    slot: Mapped[str] = mapped_column(String(16))
    value: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text)
    decision_ids_json: Mapped[list[str] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ReviewerLabReportRecord(Base):
    __tablename__ = "reviewer_lab_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    round_id: Mapped[str] = mapped_column(
        ForeignKey("reviewer_lab_rounds.id", ondelete="CASCADE"), unique=True
    )
    content_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    content_sha256: Mapped[str] = mapped_column(String(64))
