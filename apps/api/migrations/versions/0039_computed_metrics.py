"""Add immutable computed metric definitions and results.

Revision ID: 0039
Revises: 0038
"""

import sqlalchemy as sa
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "computed_metric_definitions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("expression", sa.String(1000), nullable=False),
        sa.Column("formula_version", sa.String(100), nullable=False),
        sa.Column("input_spec_json", sa.JSON(), nullable=False),
        sa.Column("output_unit", sa.String(50), nullable=False),
        sa.Column("definition_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_computed_metric_definition_project",
        "computed_metric_definitions",
        ["project_id", "created_at"],
    )
    op.create_table(
        "computed_metric_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "definition_id",
            sa.String(36),
            sa.ForeignKey("computed_metric_definitions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column(
            "workflow_run_id",
            sa.String(36),
            sa.ForeignKey("workflow_runs.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "workflow_node_run_id",
            sa.String(36),
            sa.ForeignKey("workflow_node_runs.id", ondelete="RESTRICT"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "workflow_node_run_id", name="uq_computed_metric_result_workflow_node_run"
        ),
    )
    op.create_index(
        "ix_computed_metric_result_project",
        "computed_metric_results",
        ["project_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_computed_metric_result_project", table_name="computed_metric_results")
    op.drop_table("computed_metric_results")
    op.drop_index("ix_computed_metric_definition_project", table_name="computed_metric_definitions")
    op.drop_table("computed_metric_definitions")
