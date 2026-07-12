"""Add immutable dataset versions and export records.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dataset_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("parent_version_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("requested_split_method", sa.String(length=30), nullable=False),
        sa.Column("resolved_split_method", sa.String(length=30), nullable=False),
        sa.Column("eligible_annotation_statuses_json", sa.JSON(), nullable=False),
        sa.Column("requested_ratios_json", sa.JSON(), nullable=True),
        sa.Column("achieved_ratios_json", sa.JSON(), nullable=True),
        sa.Column("split_seed", sa.Integer(), nullable=True),
        sa.Column(
            "reuse_parent_assignments",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("missing_group_key_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.Column("class_map_json", sa.JSON(), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("image_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("annotation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("reefvision_version", sa.String(length=30), nullable=False),
        sa.Column("schema_version", sa.String(length=20), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["parent_version_id"], ["dataset_versions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "version_number", name="uq_dataset_versions_project_number"
        ),
    )
    op.create_index(
        "ix_dataset_versions_project_status",
        "dataset_versions",
        ["project_id", "status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dataset_versions_project_id"),
        "dataset_versions",
        ["project_id"],
        unique=False,
    )

    op.create_table(
        "dataset_version_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("dataset_version_id", sa.String(length=36), nullable=False),
        sa.Column("image_id", sa.String(length=36), nullable=False),
        sa.Column("image_sha256", sa.String(length=64), nullable=False),
        sa.Column("original_filename", sa.String(length=500), nullable=False),
        sa.Column("width_px", sa.Integer(), nullable=False),
        sa.Column("height_px", sa.Integer(), nullable=False),
        sa.Column("image_annotation_status", sa.String(length=30), nullable=False),
        sa.Column("split", sa.String(length=20), nullable=False),
        sa.Column("group_key", sa.String(length=300), nullable=True),
        sa.Column("annotation_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("per_class_counts_json", sa.JSON(), nullable=False),
        sa.Column("annotation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["image_id"], ["images.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "dataset_version_id",
            "image_id",
            name="uq_dataset_version_items_version_image",
        ),
    )
    op.create_index(
        "ix_dataset_version_items_version_group",
        "dataset_version_items",
        ["dataset_version_id", "group_key"],
        unique=False,
    )
    op.create_index(
        "ix_dataset_version_items_version_split",
        "dataset_version_items",
        ["dataset_version_id", "split"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dataset_version_items_dataset_version_id"),
        "dataset_version_items",
        ["dataset_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dataset_version_items_image_id"),
        "dataset_version_items",
        ["image_id"],
        unique=False,
    )

    op.create_table(
        "exports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("dataset_version_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=True),
        sa.Column("format", sa.String(length=60), nullable=False),
        sa.Column("output_path", sa.String(length=700), nullable=False),
        sa.Column("manifest_path", sa.String(length=700), nullable=False),
        sa.Column("archive_path", sa.String(length=700), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_exports_project_status",
        "exports",
        ["project_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_exports_version_status",
        "exports",
        ["dataset_version_id", "status"],
        unique=False,
    )
    op.create_index(op.f("ix_exports_project_id"), "exports", ["project_id"], unique=False)
    op.create_index(
        op.f("ix_exports_dataset_version_id"),
        "exports",
        ["dataset_version_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_exports_dataset_version_id"), table_name="exports")
    op.drop_index(op.f("ix_exports_project_id"), table_name="exports")
    op.drop_index("ix_exports_version_status", table_name="exports")
    op.drop_index("ix_exports_project_status", table_name="exports")
    op.drop_table("exports")

    op.drop_index(op.f("ix_dataset_version_items_image_id"), table_name="dataset_version_items")
    op.drop_index(
        op.f("ix_dataset_version_items_dataset_version_id"),
        table_name="dataset_version_items",
    )
    op.drop_index("ix_dataset_version_items_version_split", table_name="dataset_version_items")
    op.drop_index("ix_dataset_version_items_version_group", table_name="dataset_version_items")
    op.drop_table("dataset_version_items")

    op.drop_index(op.f("ix_dataset_versions_project_id"), table_name="dataset_versions")
    op.drop_index("ix_dataset_versions_project_status", table_name="dataset_versions")
    op.drop_table("dataset_versions")
