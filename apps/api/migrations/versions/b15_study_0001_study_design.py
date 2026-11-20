"""Store immutable experimental study designs and paired evidence bindings.

Revision ID: b15_study_0001
Revises: b14_condition_0041
"""

import sqlalchemy as sa
from alembic import op

revision: str = "b15_study_0001"
down_revision: str = "b14_condition_0041"
branch_labels: tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "study_design_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("design_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column(
            "supersedes_revision_id",
            sa.String(36),
            sa.ForeignKey("study_design_revisions.id", ondelete="CASCADE"),
            unique=True,
        ),
        sa.Column(
            "growth_analysis_id",
            sa.String(36),
            sa.ForeignKey("ecology_analysis_records.id", ondelete="RESTRICT"),
        ),
        sa.Column("growth_source_sha256", sa.String(64)),
        sa.Column("snapshot_json", sa.JSON, nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("source_id_map_json", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "design_id", "revision", name="uq_study_design_revision"),
    )
    op.create_index(
        "ix_study_design_project_created", "study_design_revisions", ["project_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_study_design_project_created", table_name="study_design_revisions")
    op.drop_table("study_design_revisions")
