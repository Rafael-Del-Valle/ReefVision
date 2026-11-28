"""Create immutable project-scoped 3D original-file records.

Revision ID: 0038
Revises: 0037
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "spatial_source_assets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("original_filename", sa.String(length=500), nullable=False),
        sa.Column("source_format", sa.String(length=10), nullable=False),
        sa.Column("source_kind", sa.String(length=40), nullable=False),
        sa.Column("managed_path", sa.String(length=700), nullable=False, unique=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.CheckConstraint("size_bytes > 0", name="ck_spatial_source_nonempty"),
        sa.UniqueConstraint(
            "project_id",
            "sha256",
            "source_format",
            name="uq_spatial_source_project_digest_format",
        ),
    )
    op.create_index("ix_spatial_source_assets_project_id", "spatial_source_assets", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_spatial_source_assets_project_id", table_name="spatial_source_assets")
    op.drop_table("spatial_source_assets")
