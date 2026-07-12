"""Add manual bounding-box annotation persistence.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("images") as batch_op:
        batch_op.add_column(
            sa.Column(
                "annotation_revision",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )

    op.create_table(
        "annotations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("image_id", sa.String(length=36), nullable=False),
        sa.Column("label_class_id", sa.String(length=36), nullable=False),
        sa.Column("x_min", sa.Float(), nullable=False),
        sa.Column("y_min", sa.Float(), nullable=False),
        sa.Column("x_max", sa.Float(), nullable=False),
        sa.Column("y_max", sa.Float(), nullable=False),
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("source_model_id", sa.String(length=36), nullable=True),
        sa.Column("source_prediction_id", sa.String(length=36), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["image_id"], ["images.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["label_class_id"], ["label_classes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_annotations_image_id"), "annotations", ["image_id"], unique=False)
    op.create_index(
        op.f("ix_annotations_label_class_id"), "annotations", ["label_class_id"], unique=False
    )
    op.create_index(
        "ix_annotations_image_deleted", "annotations", ["image_id", "deleted_at"], unique=False
    )
    op.create_index(
        "ix_annotations_image_label_deleted",
        "annotations",
        ["image_id", "label_class_id", "deleted_at"],
        unique=False,
    )

    op.create_table(
        "annotation_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("annotation_id", sa.String(length=36), nullable=False),
        sa.Column("image_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=30), nullable=False),
        sa.Column("before_json", sa.JSON(), nullable=True),
        sa.Column("after_json", sa.JSON(), nullable=True),
        sa.Column("actor", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["annotation_id"], ["annotations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["image_id"], ["images.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_annotation_events_image_id"), "annotation_events", ["image_id"], unique=False
    )
    op.create_index(
        "ix_annotation_events_annotation_created",
        "annotation_events",
        ["annotation_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_annotation_events_image_created",
        "annotation_events",
        ["image_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_annotation_events_image_created", table_name="annotation_events")
    op.drop_index("ix_annotation_events_annotation_created", table_name="annotation_events")
    op.drop_index(op.f("ix_annotation_events_image_id"), table_name="annotation_events")
    op.drop_table("annotation_events")

    op.drop_index("ix_annotations_image_label_deleted", table_name="annotations")
    op.drop_index("ix_annotations_image_deleted", table_name="annotations")
    op.drop_index(op.f("ix_annotations_label_class_id"), table_name="annotations")
    op.drop_index(op.f("ix_annotations_image_id"), table_name="annotations")
    op.drop_table("annotations")

    with op.batch_alter_table("images") as batch_op:
        batch_op.drop_column("annotation_revision")
