"""Invalidate coordinates created before the projection-stability guard.

Revision ID: 0030
Revises: 0029
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    observations = sa.table(
        "geo_referenced_observations",
        sa.column("is_stale", sa.Boolean()),
        sa.column("stale_reason", sa.String(length=100)),
        sa.column("stale_at", sa.DateTime(timezone=True)),
    )

    op.execute(
        observations.update()
        .where(observations.c.is_stale.is_(False))
        .values(
            is_stale=True,
            stale_reason="projection_stability_policy_changed",
            stale_at=sa.func.current_timestamp(),
        )
    )


def downgrade() -> None:
    # Staleness is intentionally not reversed. Coordinates produced
    # under the older projection-validity policy should not silently
    # become authoritative again after a downgrade.
    pass
