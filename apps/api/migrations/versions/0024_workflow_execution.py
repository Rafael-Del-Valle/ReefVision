"""Add workflow graph, run, node-run, and artifact persistence.

Revision ID: 0024
Revises: 0023
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_graph_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("graph_key", sa.String(100), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("graph_json", sa.JSON(), nullable=False),
        sa.Column("graph_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("project_id", "graph_key", "revision", name="uq_workflow_graph_revision"),
    )
    op.create_index(
        "ix_workflow_graph_records_project_key",
        "workflow_graph_records",
        ["project_id", "graph_key", "revision"],
    )

    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("workflow_graph_record_id", sa.String(36), nullable=False),
        sa.Column("job_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("graph_sha256", sa.String(64), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workflow_graph_record_id"], ["workflow_graph_records.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_workflow_runs_project_created",
        "workflow_runs",
        ["project_id", "created_at"],
    )
    op.create_index(
        "ix_workflow_runs_status_created",
        "workflow_runs",
        ["status", "created_at"],
    )

    op.create_table(
        "workflow_node_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workflow_run_id", sa.String(36), nullable=False),
        sa.Column("node_id", sa.String(100), nullable=False),
        sa.Column("node_type", sa.String(100), nullable=False),
        sa.Column("execution_order", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("parameters_json", sa.JSON(), nullable=False),
        sa.Column("input_artifact_ids_json", sa.JSON(), nullable=False),
        sa.Column("output_artifact_ids_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workflow_run_id", "node_id", name="uq_workflow_node_run_node"),
    )
    op.create_index(
        "ix_workflow_node_runs_run_order",
        "workflow_node_runs",
        ["workflow_run_id", "execution_order"],
    )

    op.create_table(
        "workflow_artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workflow_run_id", sa.String(36), nullable=False),
        sa.Column("producer_node_run_id", sa.String(36), nullable=False),
        sa.Column("producer_port_id", sa.String(100), nullable=False),
        sa.Column("data_type", sa.String(100), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["producer_node_run_id"], ["workflow_node_runs.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_workflow_artifacts_run_type",
        "workflow_artifacts",
        ["workflow_run_id", "data_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_artifacts_run_type", table_name="workflow_artifacts")
    op.drop_table("workflow_artifacts")
    op.drop_index("ix_workflow_node_runs_run_order", table_name="workflow_node_runs")
    op.drop_table("workflow_node_runs")
    op.drop_index("ix_workflow_runs_status_created", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_project_created", table_name="workflow_runs")
    op.drop_table("workflow_runs")
    op.drop_index("ix_workflow_graph_records_project_key", table_name="workflow_graph_records")
    op.drop_table("workflow_graph_records")
