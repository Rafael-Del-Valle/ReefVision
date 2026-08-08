"""Add classification workflow persistence.

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("image_labels") as batch_op:
        batch_op.add_column(sa.Column("source_model_id", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("source_prediction_id", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("provenance_json", sa.JSON(), nullable=True))
        batch_op.add_column(
            sa.Column("created_by", sa.String(100), nullable=False, server_default="local_user")
        )
        batch_op.add_column(sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            )
        )
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index(
            "ix_image_labels_image_set_deleted",
            ["image_id", "label_set", "deleted_at"],
            unique=False,
        )

    op.create_table(
        "classification_datasets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("dataset_version_id", sa.String(36), nullable=False),
        sa.Column("mode", sa.String(30), nullable=False),
        sa.Column("label_set", sa.String(100), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("output_path", sa.String(700), nullable=False),
        sa.Column("archive_path", sa.String(700), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_versions.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "project_id", "manifest_sha256", name="uq_classification_dataset_manifest"
        ),
    )
    op.create_index(
        "ix_classification_datasets_project_created",
        "classification_datasets",
        ["project_id", "created_at"],
    )

    op.create_table(
        "classification_predictions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("image_id", sa.String(36), nullable=False),
        sa.Column("model_id", sa.String(36), nullable=False),
        sa.Column("label_class_id", sa.String(36), nullable=False),
        sa.Column("label_set", sa.String(100), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("scores_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("accepted_image_label_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(100), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["image_id"], ["images.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["model_id"], ["model_registrations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["label_class_id"], ["label_classes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["accepted_image_label_id"], ["image_labels.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_classification_predictions_image_status",
        "classification_predictions",
        ["image_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_classification_predictions_image_status",
        table_name="classification_predictions",
    )
    op.drop_table("classification_predictions")
    op.drop_index(
        "ix_classification_datasets_project_created",
        table_name="classification_datasets",
    )
    op.drop_table("classification_datasets")
    with op.batch_alter_table("image_labels") as batch_op:
        batch_op.drop_index("ix_image_labels_image_set_deleted")
        batch_op.drop_column("deleted_at")
        batch_op.drop_column("updated_at")
        batch_op.drop_column("revision")
        batch_op.drop_column("created_by")
        batch_op.drop_column("provenance_json")
        batch_op.drop_column("source_prediction_id")
        batch_op.drop_column("source_model_id")
