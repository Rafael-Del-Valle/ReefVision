"""Add backup records and allow app-scoped background jobs.

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.alter_column("project_id", existing_type=sa.String(length=36), nullable=True)

    op.create_table(
        "backup_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("format_version", sa.String(length=20), nullable=False),
        sa.Column("destination_path", sa.String(length=700), nullable=False),
        sa.Column("staging_path", sa.String(length=700), nullable=True),
        sa.Column("manifest_path", sa.String(length=700), nullable=False),
        sa.Column("completion_marker_path", sa.String(length=700), nullable=False),
        sa.Column("database_filename", sa.String(length=120), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("destination_path", name="uq_backup_records_destination_path"),
        sa.UniqueConstraint("job_id", name="uq_backup_records_job_id"),
    )
    op.create_index(
        "ix_backup_records_status_created",
        "backup_records",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(op.f("ix_backup_records_job_id"), "backup_records", ["job_id"], unique=False)
    op.create_index(op.f("ix_backup_records_status"), "backup_records", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_backup_records_status"), table_name="backup_records")
    op.drop_index(op.f("ix_backup_records_job_id"), table_name="backup_records")
    op.drop_index("ix_backup_records_status_created", table_name="backup_records")
    op.drop_table("backup_records")

    op.execute(sa.text("DELETE FROM jobs WHERE project_id IS NULL"))
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.alter_column("project_id", existing_type=sa.String(length=36), nullable=False)
