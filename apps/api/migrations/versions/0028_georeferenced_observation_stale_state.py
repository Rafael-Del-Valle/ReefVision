"""Add configuration identity and stale state to geographic observations.

Revision ID: 0028
Revises: 0027
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "geo_referenced_observations",
        sa.Column(
            "configuration_hash",
            sa.String(length=64),
            nullable=True,
        ),
    )
    op.add_column(
        "geo_referenced_observations",
        sa.Column(
            "is_stale",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "geo_referenced_observations",
        sa.Column(
            "stale_reason",
            sa.String(length=100),
            nullable=True,
        ),
    )
    op.add_column(
        "geo_referenced_observations",
        sa.Column(
            "stale_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    observations = sa.table(
        "geo_referenced_observations",
        sa.column("configuration_hash", sa.String(length=64)),
        sa.column("is_stale", sa.Boolean()),
        sa.column("stale_reason", sa.String(length=100)),
        sa.column("stale_at", sa.DateTime(timezone=True)),
    )

    op.execute(
        observations.update()
        .where(observations.c.configuration_hash.is_(None))
        .values(
            is_stale=True,
            stale_reason="legacy_unfingerprinted",
            stale_at=sa.func.current_timestamp(),
        )
    )

    op.create_index(
        "ix_geo_referenced_observations_video_stale",
        "geo_referenced_observations",
        ["video_id", "is_stale"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_geo_referenced_observations_video_stale",
        table_name="geo_referenced_observations",
    )

    op.drop_column(
        "geo_referenced_observations",
        "stale_at",
    )
    op.drop_column(
        "geo_referenced_observations",
        "stale_reason",
    )
    op.drop_column(
        "geo_referenced_observations",
        "is_stale",
    )
    op.drop_column(
        "geo_referenced_observations",
        "configuration_hash",
    )
