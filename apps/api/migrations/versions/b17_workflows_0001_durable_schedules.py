"""Store local schedules and bind each due UTC slot to one workflow run."""

import sqlalchemy as sa
from alembic import op

revision = "b17_workflows_0001"
down_revision = "b16_integrated_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_schedules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("purpose", sa.String(20), nullable=False),
        sa.Column(
            "workflow_graph_record_id",
            sa.String(36),
            sa.ForeignKey("workflow_graph_records.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("graph_sha256", sa.String(64), nullable=False),
        sa.Column("inputs_json", sa.JSON(), nullable=False),
        sa.Column("inputs_sha256", sa.String(64), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("minimum_free_bytes", sa.BigInteger(), nullable=False),
        sa.Column("last_status", sa.String(32), nullable=False),
        sa.Column("last_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("interval_seconds > 0", name="ck_workflow_schedule_interval"),
        sa.CheckConstraint("minimum_free_bytes >= 0", name="ck_workflow_schedule_storage"),
    )
    op.create_index("ix_workflow_schedules_due", "workflow_schedules", ["enabled", "next_due_at"])
    op.create_index(
        "ix_workflow_schedules_project", "workflow_schedules", ["project_id", "created_at", "id"]
    )
    op.create_table(
        "workflow_schedule_occurrences",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "schedule_id",
            sa.String(36),
            sa.ForeignKey("workflow_schedules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("missed_intervals", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("detail", sa.Text()),
        sa.Column(
            "workflow_run_id", sa.String(36), sa.ForeignKey("workflow_runs.id", ondelete="RESTRICT")
        ),
        sa.Column("graph_sha256", sa.String(64), nullable=False),
        sa.Column("inputs_sha256", sa.String(64), nullable=False),
        sa.UniqueConstraint("schedule_id", "scheduled_at", name="uq_workflow_occurrence_slot"),
        sa.UniqueConstraint("workflow_run_id", name="uq_workflow_occurrence_run"),
        sa.CheckConstraint("missed_intervals >= 0", name="ck_workflow_occurrence_missed"),
    )
    op.create_index(
        "ix_workflow_occurrences_project",
        "workflow_schedule_occurrences",
        ["project_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("workflow_schedule_occurrences")
    op.drop_table("workflow_schedules")
