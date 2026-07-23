"""Add immutable classification dataset snapshots.

Revision ID: 0034
Revises: 0033
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "classification_dataset_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("label_set_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("target_kind", sa.String(length=30), nullable=False),
        sa.Column("cardinality", sa.String(length=20), nullable=False),
        sa.Column("split_seed", sa.Integer(), nullable=False),
        sa.Column("requested_ratios_json", sa.JSON(), nullable=False),
        sa.Column("achieved_ratios_json", sa.JSON(), nullable=False),
        sa.Column("class_map_json", sa.JSON(), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("target_count", sa.Integer(), nullable=False),
        sa.Column("class_count", sa.Integer(), nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["label_set_id"], ["classification_label_sets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_classification_dataset_snapshots_project_target_created",
        "classification_dataset_snapshots",
        ["project_id", "target_kind", "created_at"],
    )
    op.create_index(
        "ix_classification_dataset_snapshots_label_set_status",
        "classification_dataset_snapshots",
        ["label_set_id", "status"],
    )
    op.create_index(
        op.f("ix_classification_dataset_snapshots_project_id"),
        "classification_dataset_snapshots",
        ["project_id"],
    )
    op.create_index(
        op.f("ix_classification_dataset_snapshots_label_set_id"),
        "classification_dataset_snapshots",
        ["label_set_id"],
    )
    op.create_index(
        op.f("ix_classification_dataset_snapshots_manifest_sha256"),
        "classification_dataset_snapshots",
        ["manifest_sha256"],
    )

    op.create_table(
        "classification_dataset_samples",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("target_kind", sa.String(length=30), nullable=False),
        sa.Column("target_key", sa.String(length=500), nullable=False),
        sa.Column("image_id", sa.String(length=36), nullable=False),
        sa.Column("mask_annotation_id", sa.String(length=36), nullable=True),
        sa.Column("fragment_key", sa.String(length=300), nullable=True),
        sa.Column("split", sa.String(length=20), nullable=False),
        sa.Column("group_key", sa.String(length=300), nullable=False),
        sa.Column("label_class_ids_json", sa.JSON(), nullable=False),
        sa.Column("assignment_ids_json", sa.JSON(), nullable=False),
        sa.Column("assignment_revisions_json", sa.JSON(), nullable=False),
        sa.Column("source_image_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_image_managed_path", sa.String(length=700), nullable=False),
        sa.Column("source_image_width_px", sa.Integer(), nullable=False),
        sa.Column("source_image_height_px", sa.Integer(), nullable=False),
        sa.Column("target_revision", sa.Integer(), nullable=True),
        sa.Column("target_checksum", sa.String(length=64), nullable=False),
        sa.Column("geometry_json", sa.JSON(), nullable=False),
        sa.Column("provenance_json", sa.JSON(), nullable=False),
        sa.Column("sample_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["image_id"], ["images.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["mask_annotation_id"], ["mask_annotations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["classification_dataset_snapshots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "snapshot_id",
            "target_key",
            name="uq_classification_dataset_samples_snapshot_target",
        ),
    )
    op.create_index(
        "ix_classification_dataset_samples_snapshot_split",
        "classification_dataset_samples",
        ["snapshot_id", "split"],
    )
    op.create_index(
        "ix_classification_dataset_samples_snapshot_group",
        "classification_dataset_samples",
        ["snapshot_id", "group_key"],
    )
    op.create_index(
        op.f("ix_classification_dataset_samples_snapshot_id"),
        "classification_dataset_samples",
        ["snapshot_id"],
    )
    op.create_index(
        op.f("ix_classification_dataset_samples_image_id"),
        "classification_dataset_samples",
        ["image_id"],
    )
    op.create_index(
        op.f("ix_classification_dataset_samples_sample_sha256"),
        "classification_dataset_samples",
        ["sample_sha256"],
    )


def downgrade() -> None:
    op.drop_table("classification_dataset_samples")
    op.drop_table("classification_dataset_snapshots")
