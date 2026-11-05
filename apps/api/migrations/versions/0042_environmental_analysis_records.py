"""Add immutable composite environmental analysis definitions and results.

Revision ID: 0042
Revises: 0041
"""

import sqlalchemy as sa
from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "environmental_analysis_definitions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("analysis_kind", sa.String(50), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("configuration_json", sa.JSON(), nullable=False),
        sa.Column("calculation_version", sa.String(100), nullable=False),
        sa.Column("definition_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_environmental_analysis_definition_project_kind",
        "environmental_analysis_definitions",
        ["project_id", "analysis_kind", "created_at"],
    )
    op.create_table(
        "environmental_analysis_results",
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
            sa.ForeignKey("environmental_analysis_definitions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("analysis_kind", sa.String(50), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("input_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("source_record_ids_json", sa.JSON(), nullable=False),
        sa.Column("source_analysis_result_ids_json", sa.JSON(), nullable=False),
        sa.Column("quality_control_json", sa.JSON(), nullable=False),
        sa.Column("uncertainty_json", sa.JSON(), nullable=True),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column(
            "workflow_run_id",
            sa.String(36),
            sa.ForeignKey("workflow_runs.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "workflow_node_run_id",
            sa.String(36),
            sa.ForeignKey("workflow_node_runs.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "workflow_node_run_id", name="uq_environmental_analysis_result_workflow_node_run"
        ),
    )
    op.create_index(
        "ix_environmental_analysis_result_project_kind",
        "environmental_analysis_results",
        ["project_id", "analysis_kind", "created_at"],
    )
    op.create_index(
        "ix_environmental_analysis_result_definition",
        "environmental_analysis_results",
        ["definition_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_environmental_analysis_result_definition",
        table_name="environmental_analysis_results",
    )
    op.drop_index(
        "ix_environmental_analysis_result_project_kind",
        table_name="environmental_analysis_results",
    )
    op.drop_table("environmental_analysis_results")
    op.drop_index(
        "ix_environmental_analysis_definition_project_kind",
        table_name="environmental_analysis_definitions",
    )
    op.drop_table("environmental_analysis_definitions")
