"""Add immutable photometric recipes for still images."""

import sqlalchemy as sa
from alembic import op

revision = "b18_adjust_0001"
down_revision = "b17_monitor_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "image_adjustment_recipes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("image_id", sa.String(length=36), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("receipt_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["image_id"], ["images.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("image_id", "content_sha256", name="uq_image_adjustment_receipt"),
    )
    op.create_index(
        "ix_image_adjustments_project",
        "image_adjustment_recipes",
        ["project_id", "image_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_image_adjustments_project", table_name="image_adjustment_recipes")
    op.drop_table("image_adjustment_recipes")
