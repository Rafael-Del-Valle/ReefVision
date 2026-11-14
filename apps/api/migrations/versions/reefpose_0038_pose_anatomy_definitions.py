"""Add stable-ID anatomical definitions to pose schema revisions.

Revision ID: reefpose_0038
Revises: 0037
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "reefpose_0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pose_landmark_schema_revisions",
        sa.Column("definition_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pose_landmark_schema_revisions", "definition_json")
