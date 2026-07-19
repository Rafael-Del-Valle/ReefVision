"""Allow generated video tracks without a resolved project class.

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
    with op.batch_alter_table("video_tracks") as batch_op:
        batch_op.alter_column(
            "label_class_id",
            existing_type=sa.String(length=36),
            nullable=True,
        )
        batch_op.create_index(
            "ix_video_tracks_video_number",
            ["video_id", "track_number"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("video_tracks") as batch_op:
        batch_op.drop_index("ix_video_tracks_video_number")
        batch_op.alter_column(
            "label_class_id",
            existing_type=sa.String(length=36),
            nullable=False,
        )
