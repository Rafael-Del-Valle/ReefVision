"""Persist immutable independent ReefPose references."""

import sqlalchemy as sa
from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reefpose_references",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("parent_id", sa.String(36)),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("data_kind", sa.String(20), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["reefpose_references.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("parent_id", name="uq_reefpose_references_parent"),
    )
    op.create_index(
        "ix_reefpose_references_project_created",
        "reefpose_references",
        ["project_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("reefpose_references")
