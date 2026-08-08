"""Add managed video extraction and tracking metadata.

Revision ID: 0021
Revises: 0020
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("videos") as batch_op:
        batch_op.add_column(sa.Column("frame_directory_path", sa.String(700), nullable=True))
        batch_op.add_column(sa.Column("extraction_job_id", sa.String(36), nullable=True))
        batch_op.add_column(
            sa.Column("status", sa.String(30), nullable=False, server_default="imported")
        )
        batch_op.add_column(sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            )
        )
        batch_op.create_foreign_key(
            "fk_videos_extraction_job",
            "jobs",
            ["extraction_job_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("video_tracks") as batch_op:
        batch_op.add_column(sa.Column("source_model_id", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("source_job_id", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("metadata_json", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            )
        )
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_foreign_key(
            "fk_video_tracks_source_model",
            "model_registrations",
            ["source_model_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_video_tracks_source_job",
            "jobs",
            ["source_job_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_video_tracks_video_deleted",
            ["video_id", "deleted_at"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("video_tracks") as batch_op:
        batch_op.drop_index("ix_video_tracks_video_deleted")
        batch_op.drop_constraint("fk_video_tracks_source_job", type_="foreignkey")
        batch_op.drop_constraint("fk_video_tracks_source_model", type_="foreignkey")
        batch_op.drop_column("deleted_at")
        batch_op.drop_column("updated_at")
        batch_op.drop_column("revision")
        batch_op.drop_column("metadata_json")
        batch_op.drop_column("source_job_id")
        batch_op.drop_column("source_model_id")

    with op.batch_alter_table("videos") as batch_op:
        batch_op.drop_constraint("fk_videos_extraction_job", type_="foreignkey")
        batch_op.drop_column("updated_at")
        batch_op.drop_column("revision")
        batch_op.drop_column("status")
        batch_op.drop_column("extraction_job_id")
        batch_op.drop_column("frame_directory_path")
