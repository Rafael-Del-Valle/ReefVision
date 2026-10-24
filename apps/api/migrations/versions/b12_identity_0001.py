"""Track B 1.2 append-only ecological identity registration.

Revision ID: b12_identity_0001
Revises: 0037

Independent from unmerged 1.1 migration 0038. Reconcile Alembic heads before
combining development branches; do not cross-merge them automatically.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b12_identity_0001"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ecology_identity_revisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("organism_key", sa.String(length=100), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("parent_colony_key", sa.String(length=100), nullable=True),
        sa.Column("experimental_unit_type", sa.String(length=100), nullable=True),
        sa.Column("experimental_unit_id", sa.String(length=150), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.CheckConstraint("revision >= 1", name="ck_ecology_identity_revision"),
        sa.CheckConstraint(
            "(experimental_unit_type IS NULL AND experimental_unit_id IS NULL) OR "
            "(experimental_unit_type IS NOT NULL AND experimental_unit_id IS NOT NULL)",
            name="ck_ecology_identity_complete_unit",
        ),
        sa.UniqueConstraint(
            "project_id",
            "organism_key",
            "revision",
            name="uq_ecology_identity_project_key_revision",
        ),
    )
    op.create_index(
        "ix_ecology_identity_project_key",
        "ecology_identity_revisions",
        ["project_id", "organism_key", "revision"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ecology_identity_project_key",
        table_name="ecology_identity_revisions",
    )
    op.drop_table("ecology_identity_revisions")
