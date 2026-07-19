"""Persist active-learning retraining cycles.

Revision ID: 0027
Revises: 0026
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "active_learning_cycles",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_cycle_id",
            sa.String(length=36),
            sa.ForeignKey("active_learning_cycles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("cycle_index", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("selection_strategy", sa.String(length=80), nullable=False),
        sa.Column("annotation_budget", sa.Integer(), nullable=False),
        sa.Column("selected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reviewed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "source_model_id",
            sa.String(length=36),
            sa.ForeignKey("model_registrations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "candidate_model_id",
            sa.String(length=36),
            sa.ForeignKey("model_registrations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "promoted_model_id",
            sa.String(length=36),
            sa.ForeignKey("model_registrations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "dataset_version_id",
            sa.String(length=36),
            sa.ForeignKey("dataset_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "training_run_id",
            sa.String(length=36),
            sa.ForeignKey("training_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "review_queue_id",
            sa.String(length=36),
            sa.ForeignKey("review_queues.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("selection_config_json", sa.JSON(), nullable=False),
        sa.Column("selection_result_json", sa.JSON(), nullable=False),
        sa.Column("baseline_metrics_json", sa.JSON(), nullable=False),
        sa.Column("candidate_metrics_json", sa.JSON(), nullable=False),
        sa.Column("promotion_gates_json", sa.JSON(), nullable=False),
        sa.Column("promotion_result_json", sa.JSON(), nullable=False),
        sa.Column("stop_conditions_json", sa.JSON(), nullable=False),
        sa.Column("history_json", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "project_id",
            "cycle_index",
            name="uq_active_learning_cycles_project_index",
        ),
    )
    op.create_index(
        "ix_active_learning_cycles_project_status",
        "active_learning_cycles",
        ["project_id", "status"],
    )
    op.create_index(
        "ix_active_learning_cycles_parent",
        "active_learning_cycles",
        ["parent_cycle_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_active_learning_cycles_parent",
        table_name="active_learning_cycles",
    )
    op.drop_index(
        "ix_active_learning_cycles_project_status",
        table_name="active_learning_cycles",
    )
    op.drop_table("active_learning_cycles")
