"""Append-only local QC review comments and assignment history.

Revision ID: 0038
Revises: 0037
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_queue_item_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("review_queue_id", sa.String(length=36), nullable=False),
        sa.Column("review_queue_item_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("client_request_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("actor", sa.String(length=100), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("assignee", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["review_queue_id"], ["review_queues.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["review_queue_item_id"], ["review_queue_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "review_queue_item_id",
            "client_request_id",
            name="uq_review_queue_item_event_request",
        ),
        sa.CheckConstraint(
            "event_type IN ('comment', 'assign', 'unassign')",
            name="ck_review_queue_item_event_type",
        ),
    )
    op.create_index(
        "ix_review_queue_item_events_item_created",
        "review_queue_item_events",
        ["review_queue_item_id", "created_at"],
    )
    op.create_index(
        "ix_review_queue_item_events_queue_created",
        "review_queue_item_events",
        ["review_queue_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_review_queue_item_events_queue_created",
        table_name="review_queue_item_events",
    )
    op.drop_index(
        "ix_review_queue_item_events_item_created",
        table_name="review_queue_item_events",
    )
    op.drop_table("review_queue_item_events")
