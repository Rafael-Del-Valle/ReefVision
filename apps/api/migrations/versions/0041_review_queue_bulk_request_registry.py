"""Persist global QC bulk UUIDs to prevent simultaneous disjoint reuse.

Revision ID: 0041
Revises: 0040
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_queue_bulk_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "review_queue_id",
            sa.String(36),
            sa.ForeignKey("review_queues.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("item_ids_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    connection = op.get_bind()
    count = connection.scalar(sa.text("SELECT COUNT(*) FROM review_queue_bulk_requests"))
    if count:
        raise RuntimeError(
            "Cannot downgrade QC bulk request registry while committed request "
            "identities exist; preserve the database and audit history."
        )
    op.drop_table("review_queue_bulk_requests")
