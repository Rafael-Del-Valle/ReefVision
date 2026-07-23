"""Generalize classification predictions to images, masks, and fragments.

Revision ID: 0033
Revises: 0032
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("classification_predictions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "target_kind",
                sa.String(length=30),
                nullable=False,
                server_default=sa.text("'annotation'"),
            )
        )
        batch_op.add_column(sa.Column("target_key", sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column("mask_annotation_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("fragment_key", sa.String(length=300), nullable=True))
        batch_op.create_foreign_key(
            "fk_classification_predictions_mask_annotation_id",
            "mask_annotations",
            ["mask_annotation_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.execute(
        "UPDATE classification_predictions "
        "SET target_key = CASE "
        "WHEN annotation_id IS NOT NULL THEN 'annotation:' || annotation_id "
        "ELSE 'image:' || image_id END "
        "WHERE target_key IS NULL"
    )
    with op.batch_alter_table("classification_predictions") as batch_op:
        batch_op.alter_column(
            "target_key",
            existing_type=sa.String(length=500),
            nullable=False,
        )
    op.create_index(
        "ix_classification_predictions_target_status",
        "classification_predictions",
        ["target_kind", "target_key", "review_status"],
    )
    op.create_index(
        op.f("ix_classification_predictions_mask_annotation_id"),
        "classification_predictions",
        ["mask_annotation_id"],
    )
    op.create_index(
        op.f("ix_classification_predictions_fragment_key"),
        "classification_predictions",
        ["fragment_key"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_classification_predictions_fragment_key"),
        table_name="classification_predictions",
    )
    op.drop_index(
        op.f("ix_classification_predictions_mask_annotation_id"),
        table_name="classification_predictions",
    )
    op.drop_index(
        "ix_classification_predictions_target_status",
        table_name="classification_predictions",
    )
    with op.batch_alter_table("classification_predictions") as batch_op:
        batch_op.drop_constraint(
            "fk_classification_predictions_mask_annotation_id",
            type_="foreignkey",
        )
        batch_op.drop_column("fragment_key")
        batch_op.drop_column("mask_annotation_id")
        batch_op.drop_column("target_key")
        batch_op.drop_column("target_kind")
