"""Add reviewable segmentation geometry to prediction proposals.

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("prediction_proposals") as batch_op:
        batch_op.add_column(
            sa.Column(
                "geometry_kind",
                sa.String(length=30),
                nullable=False,
                server_default="bounding_box",
            )
        )
        batch_op.add_column(
            sa.Column(
                "polygon_json",
                sa.JSON(),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "accepted_mask_annotation_id",
                sa.String(length=36),
                nullable=True,
            )
        )
        batch_op.create_index(
            "ix_prediction_proposals_image_geometry_status",
            ["image_id", "geometry_kind", "review_status"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("prediction_proposals") as batch_op:
        batch_op.drop_index("ix_prediction_proposals_image_geometry_status")
        batch_op.drop_column("accepted_mask_annotation_id")
        batch_op.drop_column("polygon_json")
        batch_op.drop_column("geometry_kind")
