"""Add quality-control runs/issues and review queue history.

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "quality_control_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("dataset_version_id", sa.String(length=36), nullable=True),
        sa.Column("job_id", sa.String(length=36), nullable=True),
        sa.Column("scope_type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("rule_categories_json", sa.JSON(), nullable=False),
        sa.Column("selected_rule_ids_json", sa.JSON(), nullable=False),
        sa.Column("thresholds_json", sa.JSON(), nullable=False),
        sa.Column("configuration_json", sa.JSON(), nullable=False),
        sa.Column("input_checksums_json", sa.JSON(), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("issue_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_versions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_quality_control_runs_job_id"),
    )
    op.create_index(
        "ix_quality_control_runs_project_status",
        "quality_control_runs",
        ["project_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_quality_control_runs_dataset_status",
        "quality_control_runs",
        ["dataset_version_id", "status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_quality_control_runs_project_id"),
        "quality_control_runs",
        ["project_id"],
        unique=False,
    )

    op.create_table(
        "quality_control_issues",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("quality_control_run_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("dataset_version_id", sa.String(length=36), nullable=True),
        sa.Column("image_id", sa.String(length=36), nullable=True),
        sa.Column("rule_id", sa.String(length=100), nullable=False),
        sa.Column("rule_version", sa.String(length=40), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("annotation_ids_json", sa.JSON(), nullable=False),
        sa.Column("prediction_ids_json", sa.JSON(), nullable=False),
        sa.Column("class_ids_json", sa.JSON(), nullable=False),
        sa.Column("measured_values_json", sa.JSON(), nullable=False),
        sa.Column("thresholds_json", sa.JSON(), nullable=False),
        sa.Column("resolution_metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.String(length=100), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_by", sa.String(length=100), nullable=True),
        sa.Column("dismissed_reason", sa.Text(), nullable=True),
        sa.Column("resolution_run_id", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(
            ["quality_control_run_id"], ["quality_control_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_quality_control_issues_run_status",
        "quality_control_issues",
        ["quality_control_run_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_quality_control_issues_run_severity",
        "quality_control_issues",
        ["quality_control_run_id", "severity"],
        unique=False,
    )
    op.create_index(
        "ix_quality_control_issues_run_rule",
        "quality_control_issues",
        ["quality_control_run_id", "rule_id"],
        unique=False,
    )
    op.create_index(
        "ix_quality_control_issues_project_image",
        "quality_control_issues",
        ["project_id", "image_id"],
        unique=False,
    )
    op.create_index(
        "ix_quality_control_issues_fingerprint",
        "quality_control_issues",
        ["fingerprint"],
        unique=False,
    )
    op.create_index(
        op.f("ix_quality_control_issues_project_id"),
        "quality_control_issues",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_quality_control_issues_quality_control_run_id"),
        "quality_control_issues",
        ["quality_control_run_id"],
        unique=False,
    )

    op.create_table(
        "review_queues",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("dataset_version_id", sa.String(length=36), nullable=True),
        sa.Column("source_quality_control_run_id", sa.String(length=36), nullable=True),
        sa.Column("regenerated_from_queue_id", sa.String(length=36), nullable=True),
        sa.Column("scope_type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("formula_id", sa.String(length=100), nullable=False),
        sa.Column("formula_version", sa.String(length=40), nullable=False),
        sa.Column("configuration_json", sa.JSON(), nullable=False),
        sa.Column("input_checksums_json", sa.JSON(), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_versions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["regenerated_from_queue_id"], ["review_queues.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_quality_control_run_id"], ["quality_control_runs.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_review_queues_project_created",
        "review_queues",
        ["project_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_review_queues_dataset_created",
        "review_queues",
        ["dataset_version_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_review_queues_status_created",
        "review_queues",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_review_queues_project_id"),
        "review_queues",
        ["project_id"],
        unique=False,
    )

    op.create_table(
        "review_queue_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("review_queue_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("dataset_version_id", sa.String(length=36), nullable=True),
        sa.Column("image_id", sa.String(length=36), nullable=False),
        sa.Column("split", sa.String(length=20), nullable=True),
        sa.Column("review_state", sa.String(length=30), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("rank_position", sa.Integer(), nullable=False),
        sa.Column("highest_qc_severity", sa.String(length=20), nullable=True),
        sa.Column("label_class_ids_json", sa.JSON(), nullable=False),
        sa.Column("model_ids_json", sa.JSON(), nullable=False),
        sa.Column("related_issue_ids_json", sa.JSON(), nullable=False),
        sa.Column("signal_values_json", sa.JSON(), nullable=False),
        sa.Column("normalized_signals_json", sa.JSON(), nullable=False),
        sa.Column("weights_json", sa.JSON(), nullable=False),
        sa.Column("score_breakdown_json", sa.JSON(), nullable=False),
        sa.Column("input_checksum", sa.String(length=64), nullable=False),
        sa.Column("reason_summary", sa.Text(), nullable=True),
        sa.Column("skip_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("returned_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["review_queue_id"], ["review_queues.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_review_queue_items_queue_state",
        "review_queue_items",
        ["review_queue_id", "review_state"],
        unique=False,
    )
    op.create_index(
        "ix_review_queue_items_queue_score",
        "review_queue_items",
        ["review_queue_id", "score"],
        unique=False,
    )
    op.create_index(
        "ix_review_queue_items_project_image",
        "review_queue_items",
        ["project_id", "image_id"],
        unique=False,
    )
    op.create_index(
        "ix_review_queue_items_queue_severity",
        "review_queue_items",
        ["review_queue_id", "highest_qc_severity"],
        unique=False,
    )
    op.create_index(
        op.f("ix_review_queue_items_project_id"),
        "review_queue_items",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_review_queue_items_review_queue_id"),
        "review_queue_items",
        ["review_queue_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_review_queue_items_review_queue_id"),
        table_name="review_queue_items",
    )
    op.drop_index(op.f("ix_review_queue_items_project_id"), table_name="review_queue_items")
    op.drop_index("ix_review_queue_items_queue_severity", table_name="review_queue_items")
    op.drop_index("ix_review_queue_items_project_image", table_name="review_queue_items")
    op.drop_index("ix_review_queue_items_queue_score", table_name="review_queue_items")
    op.drop_index("ix_review_queue_items_queue_state", table_name="review_queue_items")
    op.drop_table("review_queue_items")

    op.drop_index(op.f("ix_review_queues_project_id"), table_name="review_queues")
    op.drop_index("ix_review_queues_status_created", table_name="review_queues")
    op.drop_index("ix_review_queues_dataset_created", table_name="review_queues")
    op.drop_index("ix_review_queues_project_created", table_name="review_queues")
    op.drop_table("review_queues")

    op.drop_index(
        op.f("ix_quality_control_issues_quality_control_run_id"),
        table_name="quality_control_issues",
    )
    op.drop_index(op.f("ix_quality_control_issues_project_id"), table_name="quality_control_issues")
    op.drop_index("ix_quality_control_issues_fingerprint", table_name="quality_control_issues")
    op.drop_index("ix_quality_control_issues_project_image", table_name="quality_control_issues")
    op.drop_index("ix_quality_control_issues_run_rule", table_name="quality_control_issues")
    op.drop_index("ix_quality_control_issues_run_severity", table_name="quality_control_issues")
    op.drop_index("ix_quality_control_issues_run_status", table_name="quality_control_issues")
    op.drop_table("quality_control_issues")

    op.drop_index(
        op.f("ix_quality_control_runs_project_id"),
        table_name="quality_control_runs",
    )
    op.drop_index("ix_quality_control_runs_dataset_status", table_name="quality_control_runs")
    op.drop_index("ix_quality_control_runs_project_status", table_name="quality_control_runs")
    op.drop_table("quality_control_runs")
