"""Add mask-aware immutable dataset snapshot fields.

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("dataset_versions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "mask_annotation_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )

    with op.batch_alter_table("dataset_version_items") as batch_op:
        batch_op.add_column(
            sa.Column(
                "mask_annotation_snapshot_json",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            )
        )
        batch_op.add_column(
            sa.Column(
                "per_mask_class_counts_json",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            )
        )
        batch_op.add_column(
            sa.Column(
                "mask_annotation_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("dataset_version_items") as batch_op:
        batch_op.drop_column("mask_annotation_count")
        batch_op.drop_column("per_mask_class_counts_json")
        batch_op.drop_column("mask_annotation_snapshot_json")

    with op.batch_alter_table("dataset_versions") as batch_op:
        batch_op.drop_column("mask_annotation_count")
