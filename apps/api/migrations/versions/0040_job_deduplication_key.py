"""Add active background-job deduplication keys.

Revision ID: 0040
Revises: 0039
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("deduplication_key", sa.String(length=64), nullable=True))
    op.create_index(
        "ux_jobs_deduplication_key",
        "jobs",
        ["deduplication_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ux_jobs_deduplication_key", table_name="jobs")
    op.drop_column("jobs", "deduplication_key")
