"""Append-only ecological identity to immutable image-source links.

Revision ID: b12_identity_0002
Revises: b12_identity_0001

This Track B migration remains isolated from unmerged 1.1 migration 0038.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b12_identity_0002"
down_revision: str | None = "b12_identity_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ecology_identity_image_evidence",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("organism_key", sa.String(length=100), nullable=False),
        sa.Column("identity_revision", sa.Integer(), nullable=False),
        sa.Column("image_id", sa.String(length=36), nullable=False),
        sa.Column("image_sha256", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["image_id"], ["images.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("identity_revision >= 1", name="ck_ecology_image_identity_revision"),
        sa.UniqueConstraint(
            "project_id",
            "organism_key",
            "image_id",
            name="uq_ecology_identity_image_evidence",
        ),
    )
    op.create_index(
        "ix_ecology_image_evidence_project_organism",
        "ecology_identity_image_evidence",
        ["project_id", "organism_key"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ecology_image_evidence_project_organism",
        table_name="ecology_identity_image_evidence",
    )
    op.drop_table("ecology_identity_image_evidence")
