"""Add class-operation audit records.

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "class_operations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("source_class_id", sa.String(length=36), nullable=False),
        sa.Column("target_class_id", sa.String(length=36), nullable=True),
        sa.Column("operation_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("preview_checksum", sa.String(length=64), nullable=False),
        sa.Column("requested_by_identity", sa.String(length=200), nullable=False),
        sa.Column("source_class_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("target_class_snapshot_json", sa.JSON(), nullable=True),
        sa.Column("plan_json", sa.JSON(), nullable=False),
        sa.Column("affected_counts_json", sa.JSON(), nullable=False),
        sa.Column("protected_reference_counts_json", sa.JSON(), nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.Column("failures_json", sa.JSON(), nullable=False),
        sa.Column("rollback_result_json", sa.JSON(), nullable=False),
        sa.Column("final_state", sa.String(length=60), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_class_operations_project_id",
        "class_operations",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_class_operations_preview_checksum",
        "class_operations",
        ["preview_checksum"],
        unique=False,
    )
    op.create_index(
        "ix_class_operations_source_class_id",
        "class_operations",
        ["source_class_id"],
        unique=False,
    )
    op.create_index(
        "ix_class_operations_target_class_id",
        "class_operations",
        ["target_class_id"],
        unique=False,
    )
    op.create_index(
        "ix_class_operations_project_created",
        "class_operations",
        ["project_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_class_operations_project_status",
        "class_operations",
        ["project_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_class_operations_source_target",
        "class_operations",
        ["source_class_id", "target_class_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_class_operations_source_target", table_name="class_operations")
    op.drop_index("ix_class_operations_project_status", table_name="class_operations")
    op.drop_index("ix_class_operations_project_created", table_name="class_operations")
    op.drop_index("ix_class_operations_target_class_id", table_name="class_operations")
    op.drop_index("ix_class_operations_source_class_id", table_name="class_operations")
    op.drop_index("ix_class_operations_preview_checksum", table_name="class_operations")
    op.drop_index("ix_class_operations_project_id", table_name="class_operations")
    op.drop_table("class_operations")
