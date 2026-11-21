"""Sealed appearance studies and append-only local judgements."""

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class PoseAppearanceStudy(Base):
    __tablename__ = "pose_appearance_studies"
    __table_args__ = (
        UniqueConstraint("project_id", "operation_id", name="uq_appearance_study_op"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    model_id: Mapped[str] = mapped_column(ForeignKey("model_registrations.id", ondelete="RESTRICT"))
    reference_id: Mapped[str | None] = mapped_column(
        ForeignKey("reefpose_references.id", ondelete="RESTRICT")
    )
    operation_id: Mapped[str] = mapped_column(String(36))
    request_sha256: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    content_sha256: Mapped[str] = mapped_column(String(64))
    source_id_map_json: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PoseAppearanceDecision(Base):
    __tablename__ = "pose_appearance_decisions"
    __table_args__ = (
        UniqueConstraint("study_id", "role_slot", name="uq_appearance_decision_slot"),
        UniqueConstraint("study_id", "operation_id", name="uq_appearance_decision_op"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    study_id: Mapped[str] = mapped_column(
        ForeignKey("pose_appearance_studies.id", ondelete="CASCADE"), index=True
    )
    role_revision_id: Mapped[str] = mapped_column(
        ForeignKey("reviewer_lab_role_revisions.id", ondelete="RESTRICT")
    )
    operation_id: Mapped[str] = mapped_column(String(36))
    role_slot: Mapped[str] = mapped_column(String(20))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    content_sha256: Mapped[str] = mapped_column(String(64))
    source_id_map_json: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
