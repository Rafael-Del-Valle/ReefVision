"""Milestone 0 database foundation.

Revision ID: 0001
Revises:
Create Date: 2026-07-08
"""

from collections.abc import Sequence

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Establish a tracked empty schema for Milestone 0."""


def downgrade() -> None:
    """Return to the pre-ReefVision database state."""
