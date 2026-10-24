"""Allow server-generated QC triage events without rewriting applied 0038.

Revision ID: 0039
Revises: 0038

The 0038 table check accepted only coordination events even though bulk triage
now writes triage_start/skip/return. This additive migration preserves existing
review comments and assignments and their unique-request/index contracts.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK_NAME = "ck_review_queue_item_event_type"
_OLD_TYPES = "event_type IN ('comment', 'assign', 'unassign')"
_NEW_TYPES = (
    "event_type IN ('comment', 'assign', 'unassign', "
    "'triage_start', 'triage_skip', 'triage_return')"
)


def _replace_check(expression: str) -> None:
    # SQLite cannot DROP CHECK in place. Batch mode recreates the table while
    # copying existing events and restoring named indexes and foreign keys.
    with op.batch_alter_table("review_queue_item_events", recreate="auto") as batch:
        batch.drop_constraint(_CHECK_NAME, type_="check")
        batch.create_check_constraint(_CHECK_NAME, expression)


def upgrade() -> None:
    _replace_check(_NEW_TYPES)


def downgrade() -> None:
    # A downgrade must never discard triage history or silently rewrite it as
    # comments. Refuse before attempting a table recreation if any exist.
    connection = op.get_bind()
    count = connection.scalar(
        sa.text(
            "SELECT COUNT(*) FROM review_queue_item_events "
            "WHERE event_type IN ('triage_start', 'triage_skip', 'triage_return')"
        )
    )
    if count:
        raise RuntimeError(
            "Cannot downgrade QC triage audit schema while triage events exist; "
            "preserve the database and export/review audit history first"
        )
    _replace_check(_OLD_TYPES)
