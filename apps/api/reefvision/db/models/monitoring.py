"""Immutable monitoring rules, observation windows, research decisions and comparisons."""

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


class MonitoringRule(Base):
    __tablename__ = "monitoring_rules"
    __table_args__ = (
        Index("ix_monitoring_rules_project", "project_id", "created_at", "id"),
        UniqueConstraint("project_id", "rule_sha256", name="uq_monitoring_rule_content"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(32))
    protocol: Mapped[str] = mapped_column(String(200))
    metric: Mapped[str] = mapped_column(String(100))
    unit: Mapped[str] = mapped_column(String(80))
    parameters_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    rule_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MonitoringAssessment(Base):
    __tablename__ = "monitoring_assessments"
    __table_args__ = (
        UniqueConstraint(
            "rule_id",
            "window_start",
            "window_end",
            "evidence_sha256",
            name="uq_monitoring_assessment_evidence",
        ),
        Index("ix_monitoring_assessments_project", "project_id", "created_at", "id"),
        CheckConstraint("window_end > window_start", name="ck_monitoring_assessment_window"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    rule_id: Mapped[str] = mapped_column(ForeignKey("monitoring_rules.id", ondelete="RESTRICT"))
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    evidence_sha256: Mapped[str] = mapped_column(String(64))
    result_sha256: Mapped[str] = mapped_column(String(64))
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MonitoringAlert(Base):
    __tablename__ = "monitoring_alerts"
    __table_args__ = (
        UniqueConstraint("assessment_id", "finding_key", name="uq_monitoring_alert_finding"),
        Index("ix_monitoring_alerts_project", "project_id", "created_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    assessment_id: Mapped[str] = mapped_column(
        ForeignKey("monitoring_assessments.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(50))
    finding_key: Mapped[str] = mapped_column(String(200))
    proposal_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    proposal_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MonitoringAlertReview(Base):
    __tablename__ = "monitoring_alert_reviews"
    __table_args__ = (
        UniqueConstraint("alert_id", "revision", name="uq_monitoring_alert_review_revision"),
        CheckConstraint("revision >= 1", name="ck_monitoring_alert_review_revision"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    alert_id: Mapped[str] = mapped_column(ForeignKey("monitoring_alerts.id", ondelete="CASCADE"))
    reviewer: Mapped[str] = mapped_column(String(200))
    decision: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MonitoringProjectSummary(Base):
    __tablename__ = "monitoring_project_summaries"
    __table_args__ = (
        UniqueConstraint("project_id", "content_sha256", name="uq_monitoring_summary_content"),
        Index("ix_monitoring_summaries_project", "project_id", "created_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    content_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
