"""Add active background-job deduplication keys.

Revision ID: reefpose_0040
Revises: reefpose_0039
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "reefpose_0040"
down_revision: str | None = "reefpose_0039"
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
