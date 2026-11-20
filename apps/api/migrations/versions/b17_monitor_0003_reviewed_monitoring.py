"""Store evidence windows, attributed alert decisions and local project comparisons."""

import sqlalchemy as sa
from alembic import op

revision = "b17_monitor_0003"
down_revision = "b17_acquire_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "monitoring_rules",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("protocol", sa.String(length=200), nullable=False),
        sa.Column("metric", sa.String(length=100), nullable=False),
        sa.Column("unit", sa.String(length=80), nullable=False),
        sa.Column("parameters_json", sa.JSON(), nullable=False),
        sa.Column("rule_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "rule_sha256", name="uq_monitoring_rule_content"),
    )
    op.create_index(
        "ix_monitoring_rules_project",
        "monitoring_rules",
        ["project_id", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "monitoring_assessments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("rule_id", sa.String(length=36), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_sha256", sa.String(length=64), nullable=False),
        sa.Column("result_sha256", sa.String(length=64), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("window_end > window_start", name="ck_monitoring_assessment_window"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rule_id"], ["monitoring_rules.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "rule_id",
            "window_start",
            "window_end",
            "evidence_sha256",
            name="uq_monitoring_assessment_evidence",
        ),
    )
    op.create_index(
        "ix_monitoring_assessments_project",
        "monitoring_assessments",
        ["project_id", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "monitoring_alerts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("assessment_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("finding_key", sa.String(length=200), nullable=False),
        sa.Column("proposal_json", sa.JSON(), nullable=False),
        sa.Column("proposal_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["assessment_id"], ["monitoring_assessments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "finding_key", name="uq_monitoring_alert_finding"),
    )
    op.create_index(
        "ix_monitoring_alerts_project",
        "monitoring_alerts",
        ["project_id", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "monitoring_alert_reviews",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("alert_id", sa.String(length=36), nullable=False),
        sa.Column("reviewer", sa.String(length=200), nullable=False),
        sa.Column("decision", sa.String(length=24), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision >= 1", name="ck_monitoring_alert_review_revision"),
        sa.ForeignKeyConstraint(["alert_id"], ["monitoring_alerts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("alert_id", "revision", name="uq_monitoring_alert_review_revision"),
    )
    op.create_table(
        "monitoring_project_summaries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "content_sha256", name="uq_monitoring_summary_content"),
    )
    op.create_index(
        "ix_monitoring_summaries_project",
        "monitoring_project_summaries",
        ["project_id", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("monitoring_project_summaries")
    op.drop_table("monitoring_alert_reviews")
    op.drop_table("monitoring_alerts")
    op.drop_table("monitoring_assessments")
    op.drop_table("monitoring_rules")
