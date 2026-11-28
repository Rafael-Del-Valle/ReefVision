"""Reviewed study structure joins the existing organism revision history.

Revision ID: b13_scientific_0001
Revises: b12_integrated_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b13_scientific_0001"
down_revision: str | None = "b12_integrated_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ecology_identity_revisions",
        sa.Column("study_assignment", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table("ecology_identity_revisions") as batch:
        batch.drop_column("study_assignment")
