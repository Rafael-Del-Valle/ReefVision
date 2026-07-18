"""Add project exchange package persistence.

Revision ID: 0023
Revises: 0022
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_exchange_packages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("job_id", sa.String(36), nullable=True),
        sa.Column("direction", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("format_version", sa.String(20), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("archive_path", sa.String(700), nullable=False),
        sa.Column("options_json", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_project_exchange_packages_project_created",
        "project_exchange_packages",
        ["project_id", "created_at"],
    )
    op.create_index(
        "ix_project_exchange_packages_status_created",
        "project_exchange_packages",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_project_exchange_packages_status_created",
        table_name="project_exchange_packages",
    )
    op.drop_index(
        "ix_project_exchange_packages_project_created",
        table_name="project_exchange_packages",
    )
    op.drop_table("project_exchange_packages")
