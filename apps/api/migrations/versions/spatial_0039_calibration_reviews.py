"""Persist append-only provisional spatial calibration review receipts.

Revision ID: spatial_0039
Revises: spatial_0038

This is the active alias of the unchanged draft-1.4 legacy migration retained
under ``migrations/legacy_spatial/0039_spatial_calibration_reviews.py``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "spatial_0039"
down_revision: str | None = "spatial_0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "spatial_calibration_reviews",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("spatial_source_asset_id", sa.String(length=36), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("evidence_sha256", sa.String(length=64), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["spatial_source_asset_id"], ["spatial_source_assets.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "project_id",
            "spatial_source_asset_id",
            "evidence_sha256",
            name="uq_spatial_calibration_review_evidence",
        ),
    )
    op.create_index(
        "ix_spatial_calibration_reviews_project_id",
        "spatial_calibration_reviews",
        ["project_id"],
    )
    op.create_index(
        "ix_spatial_calibration_reviews_spatial_source_asset_id",
        "spatial_calibration_reviews",
        ["spatial_source_asset_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_spatial_calibration_reviews_spatial_source_asset_id",
        table_name="spatial_calibration_reviews",
    )
    op.drop_index(
        "ix_spatial_calibration_reviews_project_id",
        table_name="spatial_calibration_reviews",
    )
    op.drop_table("spatial_calibration_reviews")
