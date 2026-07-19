"""Add reviewable classification predictions.

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
    op.create_table(
        "classification_predictions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("image_id", sa.String(length=36), nullable=False),
        sa.Column("annotation_id", sa.String(length=36), nullable=True),
        sa.Column("model_id", sa.String(length=36), nullable=False),
        sa.Column("inference_job_id", sa.String(length=36), nullable=True),
        sa.Column("label_set", sa.String(length=100), nullable=False),
        sa.Column("classification_mode", sa.String(length=40), nullable=False),
        sa.Column("x_min", sa.Float(), nullable=False),
        sa.Column("y_min", sa.Float(), nullable=False),
        sa.Column("x_max", sa.Float(), nullable=False),
        sa.Column("y_max", sa.Float(), nullable=False),
        sa.Column("predicted_label", sa.String(length=300), nullable=False),
        sa.Column("predicted_index", sa.Integer(), nullable=True),
        sa.Column("label_class_id", sa.String(length=36), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("probabilities_json", sa.JSON(), nullable=False),
        sa.Column("review_status", sa.String(length=30), nullable=False),
        sa.Column("accepted_label_class_id", sa.String(length=36), nullable=True),
        sa.Column("inference_settings_json", sa.JSON(), nullable=False),
        sa.Column("provenance_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["accepted_label_class_id"], ["label_classes.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["annotation_id"], ["annotations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["image_id"], ["images.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["inference_job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["label_class_id"], ["label_classes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["model_id"], ["model_registrations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_classification_predictions_image_status",
        "classification_predictions",
        ["image_id", "review_status"],
    )
    op.create_index(
        "ix_classification_predictions_model_created",
        "classification_predictions",
        ["model_id", "created_at"],
    )
    op.create_index(
        "ix_classification_predictions_annotation_id",
        "classification_predictions",
        ["annotation_id"],
    )
    op.create_index(
        "ix_classification_predictions_image_id",
        "classification_predictions",
        ["image_id"],
    )
    op.create_index(
        "ix_classification_predictions_inference_job_id",
        "classification_predictions",
        ["inference_job_id"],
    )
    op.create_index(
        "ix_classification_predictions_project_id",
        "classification_predictions",
        ["project_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_classification_predictions_project_id",
        table_name="classification_predictions",
    )
    op.drop_index(
        "ix_classification_predictions_inference_job_id",
        table_name="classification_predictions",
    )
    op.drop_index(
        "ix_classification_predictions_image_id",
        table_name="classification_predictions",
    )
    op.drop_index(
        "ix_classification_predictions_annotation_id",
        table_name="classification_predictions",
    )
    op.drop_index(
        "ix_classification_predictions_model_created",
        table_name="classification_predictions",
    )
    op.drop_index(
        "ix_classification_predictions_image_status",
        table_name="classification_predictions",
    )
    op.drop_table("classification_predictions")
