"""Add label-class descriptions and archive timestamps.

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("label_classes", sa.Column("description", sa.Text(), nullable=True))
    op.add_column(
        "label_classes",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE label_classes "
            "SET archived_at = CURRENT_TIMESTAMP "
            "WHERE is_active = 0 AND archived_at IS NULL"
        )
    )


def downgrade() -> None:
    op.drop_column("label_classes", "archived_at")
    op.drop_column("label_classes", "description")
