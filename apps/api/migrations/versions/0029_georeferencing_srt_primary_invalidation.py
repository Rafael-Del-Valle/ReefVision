"""Invalidate georeferencing derived under the pre-SRT-primary telemetry policy.

Revision ID: 0029
Revises: 0028
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STALE_REASON = "telemetry_selection_policy_changed"


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
            stale_reason=_STALE_REASON,
            stale_at=sa.func.current_timestamp(),
        )
    )


def downgrade() -> None:
    # Derived coordinates invalidated by a telemetry-policy change are not made
    # scientifically current again merely by downgrading application code.
    pass
