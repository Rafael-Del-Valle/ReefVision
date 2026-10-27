"""Audit successful single-item QC completion without changing scientific approval.

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

_CHECK_NAME = "ck_review_queue_item_event_type"
_OLD_TYPES = (
    "event_type IN ('comment', 'assign', 'unassign', "
    "'triage_start', 'triage_skip', 'triage_return')"
)
_NEW_TYPES = (
    "event_type IN ('comment', 'assign', 'unassign', "
    "'triage_start', 'triage_skip', 'triage_return', 'triage_complete')"
)


def _replace_check(expression: str) -> None:
    with op.batch_alter_table("review_queue_item_events", recreate="auto") as batch:
        batch.drop_constraint(_CHECK_NAME, type_="check")
        batch.create_check_constraint(_CHECK_NAME, expression)


def upgrade() -> None:
    connection = op.get_bind()
    orphan_count = connection.scalar(
        sa.text(
            "SELECT COUNT(*) FROM review_queue_item_events AS event "
            "LEFT JOIN review_queues AS queue ON queue.id = event.review_queue_id "
            "LEFT JOIN review_queue_items AS item ON item.id = event.review_queue_item_id "
            "LEFT JOIN projects AS project ON project.id = event.project_id "
            "WHERE queue.id IS NULL OR item.id IS NULL OR project.id IS NULL "
            "OR item.review_queue_id != event.review_queue_id "
            "OR item.project_id != event.project_id "
            "OR queue.project_id != event.project_id"
        )
    )
    if orphan_count:
        raise RuntimeError(
            "Cannot upgrade QC completion audit with orphan or cross-scoped events; "
            "preserve the database and repair references before retrying"
        )
    _replace_check(_NEW_TYPES)


def downgrade() -> None:
    connection = op.get_bind()
    count = connection.scalar(
        sa.text(
            "SELECT COUNT(*) FROM review_queue_item_events WHERE event_type = 'triage_complete'"
        )
    )
    if count:
        raise RuntimeError(
            "Cannot downgrade QC completion audit while completion events exist; "
            "preserve the database and review audit history first"
        )
    _replace_check(_OLD_TYPES)
