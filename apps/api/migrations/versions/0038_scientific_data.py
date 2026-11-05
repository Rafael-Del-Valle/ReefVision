"""Add project scientific records and an offline environmental cache.

Revision ID: 0038
Revises: 0037
"""

import sqlalchemy as sa
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scientific_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("variable", sa.String(100), nullable=False),
        sa.Column("source_kind", sa.String(30), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("image_id", sa.String(36), sa.ForeignKey("images.id", ondelete="RESTRICT")),
        sa.Column("video_id", sa.String(36), sa.ForeignKey("videos.id", ondelete="RESTRICT")),
        sa.Column("track_id", sa.String(36), sa.ForeignKey("video_tracks.id", ondelete="RESTRICT")),
        sa.Column("model_run_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="RESTRICT")),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_scientific_project_variable_time",
        "scientific_records",
        ["project_id", "variable", "observed_at"],
    )
    op.create_table(
        "environmental_cache_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cache_key", sa.String(64), nullable=False),
        sa.Column("source_url", sa.String(2000), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "cache_key", name="uq_environmental_cache_project_key"),
    )


def downgrade() -> None:
    op.drop_table("environmental_cache_entries")
    op.drop_index("ix_scientific_project_variable_time", table_name="scientific_records")
    op.drop_table("scientific_records")
