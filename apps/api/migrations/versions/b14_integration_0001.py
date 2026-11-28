"""Merge validated 1.3 and aliased draft-1.4 spatial histories.

Revision ID: b14_integration_0001
Revises: b13_temporal_0001, spatial_0039
"""

from collections.abc import Sequence

revision: str = "b14_integration_0001"
down_revision: tuple[str, str] = ("b13_temporal_0001", "spatial_0039")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Merge histories without rewriting either branch's schema."""


def downgrade() -> None:
    """Split the merge head while preserving both parent schemas."""
