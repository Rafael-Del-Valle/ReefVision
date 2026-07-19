"""Add aligned image depth maps.

Revision ID: 0024
Revises: 0023
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "depth_maps",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("image_id", sa.String(length=36), nullable=False),
        sa.Column("provider_id", sa.String(length=120), nullable=False),
        sa.Column("model_id", sa.String(length=500), nullable=False),
        sa.Column("model_checksum", sa.String(length=64), nullable=True),
        sa.Column("depth_kind", sa.String(length=30), nullable=False),
        sa.Column("unit", sa.String(length=30), nullable=True),
        sa.Column("managed_path", sa.String(length=800), nullable=False),
        sa.Column("preview_path", sa.String(length=800), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("width_px", sa.Integer(), nullable=False),
        sa.Column("height_px", sa.Integer(), nullable=False),
        sa.Column("minimum_depth", sa.Float(), nullable=False),
        sa.Column("maximum_depth", sa.Float(), nullable=False),
        sa.Column("median_depth", sa.Float(), nullable=False),
        sa.Column("valid_pixel_count", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["image_id"], ["images.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "image_id",
            "provider_id",
            "model_id",
            "depth_kind",
            name="uq_depth_maps_image_provider_model_kind",
        ),
        sa.UniqueConstraint("managed_path", name="uq_depth_maps_managed_path"),
    )
    op.create_index(
        "ix_depth_maps_project_image",
        "depth_maps",
        ["project_id", "image_id"],
        unique=False,
    )
    op.create_index(
        "ix_depth_maps_sha256",
        "depth_maps",
        ["sha256"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_depth_maps_sha256", table_name="depth_maps")
    op.drop_index("ix_depth_maps_project_image", table_name="depth_maps")
    op.drop_table("depth_maps")
