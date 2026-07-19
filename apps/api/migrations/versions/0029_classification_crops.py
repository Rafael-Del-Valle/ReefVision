"""Add persisted classification crop metadata.

Revision ID: 0029
Revises: 0028
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "classification_crops",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("export_id", sa.String(length=36), nullable=False),
        sa.Column("dataset_version_id", sa.String(length=36), nullable=False),
        sa.Column("image_id", sa.String(length=36), nullable=False),
        sa.Column("annotation_id", sa.String(length=36), nullable=True),
        sa.Column("label_class_id", sa.String(length=36), nullable=False),
        sa.Column("split", sa.String(length=20), nullable=False),
        sa.Column("managed_path", sa.String(length=800), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("source_box_json", sa.JSON(), nullable=False),
        sa.Column("crop_box_json", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"],
            ["dataset_versions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["export_id"],
            ["exports.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["image_id"],
            ["images.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["label_class_id"],
            ["label_classes.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "export_id",
            "managed_path",
            name="uq_classification_crops_export_path",
        ),
    )
    op.create_index(
        "ix_classification_crops_project_id",
        "classification_crops",
        ["project_id"],
    )
    op.create_index(
        "ix_classification_crops_export_id",
        "classification_crops",
        ["export_id"],
    )
    op.create_index(
        "ix_classification_crops_dataset_version_id",
        "classification_crops",
        ["dataset_version_id"],
    )
    op.create_index(
        "ix_classification_crops_image_id",
        "classification_crops",
        ["image_id"],
    )
    op.create_index(
        "ix_classification_crops_annotation_id",
        "classification_crops",
        ["annotation_id"],
    )
    op.create_index(
        "ix_classification_crops_label_class_id",
        "classification_crops",
        ["label_class_id"],
    )
    op.create_index(
        "ix_classification_crops_project_class",
        "classification_crops",
        ["project_id", "label_class_id"],
    )
    op.create_index(
        "ix_classification_crops_export_split",
        "classification_crops",
        ["export_id", "split"],
    )
    op.create_index(
        "ix_classification_crops_sha256",
        "classification_crops",
        ["sha256"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_classification_crops_sha256",
        table_name="classification_crops",
    )
    op.drop_index(
        "ix_classification_crops_export_split",
        table_name="classification_crops",
    )
    op.drop_index(
        "ix_classification_crops_project_class",
        table_name="classification_crops",
    )
    op.drop_index(
        "ix_classification_crops_label_class_id",
        table_name="classification_crops",
    )
    op.drop_index(
        "ix_classification_crops_annotation_id",
        table_name="classification_crops",
    )
    op.drop_index(
        "ix_classification_crops_image_id",
        table_name="classification_crops",
    )
    op.drop_index(
        "ix_classification_crops_dataset_version_id",
        table_name="classification_crops",
    )
    op.drop_index(
        "ix_classification_crops_export_id",
        table_name="classification_crops",
    )
    op.drop_index(
        "ix_classification_crops_project_id",
        table_name="classification_crops",
    )
    op.drop_table("classification_crops")
