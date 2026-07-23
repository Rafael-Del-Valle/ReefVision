"""Add structured classification label sets and independent assignments.

Revision ID: 0032
Revises: 0031
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "classification_label_sets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "target_kind",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'annotation'"),
        ),
        sa.Column(
            "cardinality",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'single'"),
        ),
        sa.Column(
            "allowed_class_ids_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "replaces_primary_class",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "metadata_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "key",
            name="uq_classification_label_sets_project_key",
        ),
    )
    op.create_index(
        "ix_classification_label_sets_project_target",
        "classification_label_sets",
        ["project_id", "target_kind", "is_active"],
    )
    op.create_index(
        op.f("ix_classification_label_sets_project_id"),
        "classification_label_sets",
        ["project_id"],
    )

    op.create_table(
        "classification_assignments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("label_set_id", sa.String(length=36), nullable=False),
        sa.Column("target_kind", sa.String(length=30), nullable=False),
        sa.Column("target_key", sa.String(length=500), nullable=False),
        sa.Column("image_id", sa.String(length=36), nullable=False),
        sa.Column("annotation_id", sa.String(length=36), nullable=True),
        sa.Column("mask_annotation_id", sa.String(length=36), nullable=True),
        sa.Column("fragment_key", sa.String(length=300), nullable=True),
        sa.Column("label_class_id", sa.String(length=36), nullable=False),
        sa.Column(
            "source_type",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'accepted_prediction'"),
        ),
        sa.Column("source_model_id", sa.String(length=36), nullable=True),
        sa.Column("source_prediction_id", sa.String(length=36), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "probabilities_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'accepted'"),
        ),
        sa.Column(
            "provenance_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "revision",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["label_set_id"], ["classification_label_sets.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["image_id"], ["images.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["annotation_id"], ["annotations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["mask_annotation_id"], ["mask_annotations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["label_class_id"], ["label_classes.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_model_id"], ["model_registrations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_prediction_id"],
            ["classification_predictions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_classification_assignments_target_set_status",
        "classification_assignments",
        ["target_key", "label_set_id", "status"],
    )
    op.create_index(
        "ix_classification_assignments_project_model_created",
        "classification_assignments",
        ["project_id", "source_model_id", "created_at"],
    )
    op.create_index(
        "ix_classification_assignments_image_set",
        "classification_assignments",
        ["image_id", "label_set_id"],
    )
    for column in (
        "project_id",
        "label_set_id",
        "image_id",
        "annotation_id",
        "mask_annotation_id",
        "fragment_key",
        "label_class_id",
    ):
        op.create_index(
            op.f(f"ix_classification_assignments_{column}"),
            "classification_assignments",
            [column],
        )


def downgrade() -> None:
    for column in (
        "label_class_id",
        "fragment_key",
        "mask_annotation_id",
        "annotation_id",
        "image_id",
        "label_set_id",
        "project_id",
    ):
        op.drop_index(
            op.f(f"ix_classification_assignments_{column}"),
            table_name="classification_assignments",
        )
    op.drop_index(
        "ix_classification_assignments_image_set",
        table_name="classification_assignments",
    )
    op.drop_index(
        "ix_classification_assignments_project_model_created",
        table_name="classification_assignments",
    )
    op.drop_index(
        "ix_classification_assignments_target_set_status",
        table_name="classification_assignments",
    )
    op.drop_table("classification_assignments")

    op.drop_index(
        op.f("ix_classification_label_sets_project_id"),
        table_name="classification_label_sets",
    )
    op.drop_index(
        "ix_classification_label_sets_project_target",
        table_name="classification_label_sets",
    )
    op.drop_table("classification_label_sets")
