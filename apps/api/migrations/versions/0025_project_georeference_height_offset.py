"""Add project georeferencing height offset.

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "georeference_height_offset_m",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("projects", "georeference_height_offset_m")
