"""Add immutable spatial asset metadata revisions.

Revision ID: b14_spatial_0040
Revises: b14_integration_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b14_spatial_0040"
down_revision: str | None = "b14_integration_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "spatial_asset_metadata_revisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("spatial_source_asset_id", sa.String(length=36), nullable=False),
        sa.Column("previous_revision_id", sa.String(length=36), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("coordinate_unit", sa.String(length=32), nullable=False),
        sa.Column("meters_per_unit", sa.Float(), nullable=True),
        sa.Column("coordinate_frame_id", sa.String(length=128), nullable=True),
        sa.Column("transform_to_project_frame_json", sa.JSON(), nullable=True),
        sa.Column("calibration_evidence", sa.String(length=2_000), nullable=True),
        sa.Column("review_state", sa.String(length=40), nullable=False),
        sa.Column("reviewed_by_identity", sa.String(length=128), nullable=True),
        sa.Column("review_note", sa.String(length=2_000), nullable=True),
        sa.Column("created_by_identity", sa.String(length=128), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["spatial_source_asset_id"], ["spatial_source_assets.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["previous_revision_id"],
            ["spatial_asset_metadata_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("revision > 0", name="ck_spatial_asset_metadata_revision_positive"),
        sa.UniqueConstraint(
            "spatial_source_asset_id",
            "revision",
            name="uq_spatial_asset_metadata_revision",
        ),
        sa.UniqueConstraint(
            "spatial_source_asset_id",
            "content_sha256",
            name="uq_spatial_asset_metadata_content",
        ),
    )
    op.create_index(
        "ix_spatial_asset_metadata_revisions_project_id",
        "spatial_asset_metadata_revisions",
        ["project_id"],
    )
    op.create_index(
        "ix_spatial_asset_metadata_revisions_spatial_source_asset_id",
        "spatial_asset_metadata_revisions",
        ["spatial_source_asset_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_spatial_asset_metadata_revisions_spatial_source_asset_id",
        table_name="spatial_asset_metadata_revisions",
    )
    op.drop_index(
        "ix_spatial_asset_metadata_revisions_project_id",
        table_name="spatial_asset_metadata_revisions",
    )
    op.drop_table("spatial_asset_metadata_revisions")
