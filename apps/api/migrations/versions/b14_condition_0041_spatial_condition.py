"""Persist declared biological condition rubrics and revisioned observations.

Revision ID: b14_condition_0041
Revises: b14_spatial_0040
"""

import sqlalchemy as sa
from alembic import op

revision: str = "b14_condition_0041"
down_revision: str = "b14_spatial_0040"
branch_labels: tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "spatial_condition_rubrics",
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("rubric_id", sa.String(128), primary_key=True),
        sa.Column("version", sa.String(128), primary_key=True),
        sa.Column("content_sha256", sa.String(64), nullable=False),
    )
    op.create_table(
        "spatial_condition_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "asset_id",
            sa.String(36),
            sa.ForeignKey("spatial_source_assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("observation_id", sa.String(36), nullable=False),
        sa.Column(
            "previous_revision_id",
            sa.String(36),
            sa.ForeignKey("spatial_condition_revisions.id", ondelete="CASCADE"),
            nullable=True,
            unique=True,
        ),
        sa.Column("phase", sa.String(16), nullable=False),
        sa.Column("observation_json", sa.JSON, nullable=False),
        sa.Column("decision_json", sa.JSON, nullable=True),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_spatial_condition_asset", "spatial_condition_revisions", ["project_id", "asset_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_spatial_condition_asset", table_name="spatial_condition_revisions")
    op.drop_table("spatial_condition_revisions")
    op.drop_table("spatial_condition_rubrics")
