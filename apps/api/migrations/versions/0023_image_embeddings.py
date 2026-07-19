"""Add persisted project image embeddings.

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
        "image_embeddings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("image_id", sa.String(length=36), nullable=False),
        sa.Column("embedding_model_id", sa.String(length=300), nullable=False),
        sa.Column("embedding_model_checksum", sa.String(length=64), nullable=True),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("vector_json", sa.JSON(), nullable=False),
        sa.Column("vector_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["image_id"], ["images.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "image_id",
            "embedding_model_id",
            name="uq_image_embeddings_image_model",
        ),
    )
    op.create_index(
        "ix_image_embeddings_project_model",
        "image_embeddings",
        ["project_id", "embedding_model_id"],
        unique=False,
    )
    op.create_index(
        "ix_image_embeddings_vector_sha256",
        "image_embeddings",
        ["vector_sha256"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_image_embeddings_vector_sha256",
        table_name="image_embeddings",
    )
    op.drop_index(
        "ix_image_embeddings_project_model",
        table_name="image_embeddings",
    )
    op.drop_table("image_embeddings")
