"""Freeze newly linked source image acquisition and geometry metadata.

Revision ID: b12_identity_0005
Revises: b12_identity_0004

Existing image links remain NULL/legacy_unfrozen. Never backfill an immutable
capture-time claim from mutable historical image metadata without review.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b12_identity_0005"
down_revision: str | None = "b12_identity_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ecology_identity_image_evidence",
        sa.Column("source_metadata_sha256", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ecology_identity_image_evidence", "source_metadata_sha256")
