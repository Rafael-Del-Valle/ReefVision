"""Add revisioned scientific measurement profiles to mask annotations.

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("mask_annotations") as batch_op:
        batch_op.add_column(
            sa.Column(
                "measurement_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("mask_annotations") as batch_op:
        batch_op.drop_column("measurement_json")
