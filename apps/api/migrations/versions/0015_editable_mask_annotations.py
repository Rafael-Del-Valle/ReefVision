"""Add editable mask revisions and audit events.

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("mask_annotations") as batch_op:
        batch_op.add_column(
            sa.Column(
                "created_by",
                sa.String(length=100),
                nullable=False,
                server_default="local_user",
            )
        )
        batch_op.add_column(
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("revision", sa.Integer(), nullable=False, server_default="1")
        )

    op.create_index(
        "ix_mask_annotations_image_deleted",
        "mask_annotations",
        ["image_id", "deleted_at"],
        unique=False,
    )
    op.create_index(
        "ix_mask_annotations_image_label_deleted",
        "mask_annotations",
        ["image_id", "label_class_id", "deleted_at"],
        unique=False,
    )

    op.create_table(
        "mask_annotation_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("mask_annotation_id", sa.String(length=36), nullable=False),
        sa.Column("image_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=30), nullable=False),
        sa.Column("before_json", sa.JSON(), nullable=True),
        sa.Column("after_json", sa.JSON(), nullable=True),
        sa.Column("actor", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["image_id"],
            ["images.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["mask_annotation_id"],
            ["mask_annotations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mask_annotation_events_annotation_created",
        "mask_annotation_events",
        ["mask_annotation_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_mask_annotation_events_image_created",
        "mask_annotation_events",
        ["image_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mask_annotation_events_image_id"),
        "mask_annotation_events",
        ["image_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_mask_annotation_events_image_id"),
        table_name="mask_annotation_events",
    )
    op.drop_index(
        "ix_mask_annotation_events_image_created",
        table_name="mask_annotation_events",
    )
    op.drop_index(
        "ix_mask_annotation_events_annotation_created",
        table_name="mask_annotation_events",
    )
    op.drop_table("mask_annotation_events")

    op.drop_index(
        "ix_mask_annotations_image_label_deleted",
        table_name="mask_annotations",
    )
    op.drop_index(
        "ix_mask_annotations_image_deleted",
        table_name="mask_annotations",
    )
    with op.batch_alter_table("mask_annotations") as batch_op:
        batch_op.drop_column("revision")
        batch_op.drop_column("deleted_at")
        batch_op.drop_column("created_by")
