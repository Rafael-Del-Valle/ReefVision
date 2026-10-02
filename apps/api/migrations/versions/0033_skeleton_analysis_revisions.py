"""Add skeleton analysis revision persistence.

Revision ID: 0033
Revises: 0032
"""

from collections.abc import Sequence

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
