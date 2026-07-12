"""Add Training workspace draft, run, and experiment records.

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "training_drafts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("run_name", sa.String(length=200), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("dataset_version_id", sa.String(length=36), nullable=True),
        sa.Column("dataset_manifest_sha256", sa.String(length=64), nullable=True),
        sa.Column("split_manifest_sha256", sa.String(length=64), nullable=True),
        sa.Column("task", sa.String(length=40), nullable=True),
        sa.Column("provider_id", sa.String(length=100), nullable=True),
        sa.Column("architecture", sa.String(length=200), nullable=True),
        sa.Column("initial_checkpoint_source", sa.String(length=30), nullable=False),
        sa.Column("initial_checkpoint_model_id", sa.String(length=36), nullable=True),
        sa.Column("device", sa.String(length=60), nullable=False),
        sa.Column("precision", sa.String(length=30), nullable=False),
        sa.Column("random_seed", sa.Integer(), nullable=True),
        sa.Column("tiling_config_json", sa.JSON(), nullable=False),
        sa.Column("training_config_json", sa.JSON(), nullable=False),
        sa.Column("tuning_config_json", sa.JSON(), nullable=False),
        sa.Column("evaluation_config_json", sa.JSON(), nullable=False),
        sa.Column("resource_limits_json", sa.JSON(), nullable=False),
        sa.Column("validation_state_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_versions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["initial_checkpoint_model_id"], ["model_registrations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_training_drafts_project_id"), "training_drafts", ["project_id"], unique=False
    )
    op.create_index(
        "ix_training_drafts_project_updated",
        "training_drafts",
        ["project_id", "updated_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_training_drafts_dataset_version_id"),
        "training_drafts",
        ["dataset_version_id"],
        unique=False,
    )

    op.create_table(
        "training_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("draft_id", sa.String(length=36), nullable=True),
        sa.Column("dataset_version_id", sa.String(length=36), nullable=True),
        sa.Column("dataset_manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("split_manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("task", sa.String(length=40), nullable=False),
        sa.Column("provider_id", sa.String(length=100), nullable=False),
        sa.Column("architecture", sa.String(length=200), nullable=False),
        sa.Column("initial_checkpoint_source", sa.String(length=30), nullable=False),
        sa.Column("initial_checkpoint_model_id", sa.String(length=36), nullable=True),
        sa.Column("device", sa.String(length=60), nullable=False),
        sa.Column("precision", sa.String(length=30), nullable=False),
        sa.Column("run_name", sa.String(length=200), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("random_seed", sa.Integer(), nullable=True),
        sa.Column("tiling_config_json", sa.JSON(), nullable=False),
        sa.Column("training_config_json", sa.JSON(), nullable=False),
        sa.Column("tuning_config_json", sa.JSON(), nullable=False),
        sa.Column("evaluation_config_json", sa.JSON(), nullable=False),
        sa.Column("resource_limits_json", sa.JSON(), nullable=False),
        sa.Column("preflight_report_json", sa.JSON(), nullable=False),
        sa.Column("draft_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("stage", sa.String(length=60), nullable=False),
        sa.Column("progress_epoch", sa.Integer(), nullable=False),
        sa.Column("progress_total_epochs", sa.Integer(), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("metrics_history_json", sa.JSON(), nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.Column("artifact_manifest_json", sa.JSON(), nullable=False),
        sa.Column("logs_path", sa.String(length=700), nullable=True),
        sa.Column("result_checkpoint_path", sa.String(length=700), nullable=True),
        sa.Column("job_id", sa.String(length=36), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_versions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["draft_id"], ["training_drafts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["initial_checkpoint_model_id"], ["model_registrations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_training_runs_job_id"),
    )
    op.create_index(
        op.f("ix_training_runs_project_id"), "training_runs", ["project_id"], unique=False
    )
    op.create_index(op.f("ix_training_runs_draft_id"), "training_runs", ["draft_id"], unique=False)
    op.create_index(
        op.f("ix_training_runs_dataset_version_id"),
        "training_runs",
        ["dataset_version_id"],
        unique=False,
    )
    op.create_index(op.f("ix_training_runs_job_id"), "training_runs", ["job_id"], unique=False)
    op.create_index(
        "ix_training_runs_project_created",
        "training_runs",
        ["project_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_training_runs_project_status",
        "training_runs",
        ["project_id", "status"],
        unique=False,
    )

    op.create_table(
        "experiment_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("training_run_id", sa.String(length=36), nullable=False),
        sa.Column("dataset_version_id", sa.String(length=36), nullable=True),
        sa.Column("dataset_manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("split_manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("task", sa.String(length=40), nullable=False),
        sa.Column("provider_id", sa.String(length=100), nullable=False),
        sa.Column("architecture", sa.String(length=200), nullable=False),
        sa.Column("summary_metrics_json", sa.JSON(), nullable=False),
        sa.Column("comparison_warnings_json", sa.JSON(), nullable=False),
        sa.Column("artifact_manifest_json", sa.JSON(), nullable=False),
        sa.Column("package_versions_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_versions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["training_run_id"], ["training_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("training_run_id", name="uq_experiment_records_training_run_id"),
    )
    op.create_index(
        op.f("ix_experiment_records_project_id"),
        "experiment_records",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_experiment_records_training_run_id"),
        "experiment_records",
        ["training_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_experiment_records_dataset_version_id"),
        "experiment_records",
        ["dataset_version_id"],
        unique=False,
    )
    op.create_index(
        "ix_experiment_records_project_created",
        "experiment_records",
        ["project_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_experiment_records_project_created", table_name="experiment_records")
    op.drop_index(op.f("ix_experiment_records_dataset_version_id"), table_name="experiment_records")
    op.drop_index(op.f("ix_experiment_records_training_run_id"), table_name="experiment_records")
    op.drop_index(op.f("ix_experiment_records_project_id"), table_name="experiment_records")
    op.drop_table("experiment_records")

    op.drop_index("ix_training_runs_project_status", table_name="training_runs")
    op.drop_index("ix_training_runs_project_created", table_name="training_runs")
    op.drop_index(op.f("ix_training_runs_job_id"), table_name="training_runs")
    op.drop_index(op.f("ix_training_runs_dataset_version_id"), table_name="training_runs")
    op.drop_index(op.f("ix_training_runs_draft_id"), table_name="training_runs")
    op.drop_index(op.f("ix_training_runs_project_id"), table_name="training_runs")
    op.drop_table("training_runs")

    op.drop_index(op.f("ix_training_drafts_dataset_version_id"), table_name="training_drafts")
    op.drop_index("ix_training_drafts_project_updated", table_name="training_drafts")
    op.drop_index(op.f("ix_training_drafts_project_id"), table_name="training_drafts")
    op.drop_table("training_drafts")
