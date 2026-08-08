"""Add immutable raster-mask payloads to prediction proposals.

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("prediction_proposals") as batch_op:
        batch_op.add_column(
            sa.Column(
                "mask_path",
                sa.String(length=700),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "mask_content_sha256",
                sa.String(length=64),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("prediction_proposals") as batch_op:
        batch_op.drop_column("mask_content_sha256")
        batch_op.drop_column("mask_path")
