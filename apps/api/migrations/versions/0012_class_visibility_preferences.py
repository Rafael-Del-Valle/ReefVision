"""Add class-visibility preference and project-default tables.

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "class_visibility_preferences",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("user_identity", sa.String(length=200), nullable=False),
        sa.Column("layer_type", sa.String(length=50), nullable=False),
        sa.Column("hidden_class_ids_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "user_identity",
            "layer_type",
            name="uq_class_visibility_preferences_scope",
        ),
    )
    op.create_index(
        "ix_class_visibility_preferences_project_id",
        "class_visibility_preferences",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_class_visibility_preferences_project_user",
        "class_visibility_preferences",
        ["project_id", "user_identity"],
        unique=False,
    )

    op.create_table(
        "project_class_visibility_defaults",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("layer_type", sa.String(length=50), nullable=False),
        sa.Column("hidden_class_ids_json", sa.JSON(), nullable=False),
        sa.Column("updated_by_identity", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "layer_type",
            name="uq_project_class_visibility_defaults_scope",
        ),
    )
    op.create_index(
        "ix_project_class_visibility_defaults_project",
        "project_class_visibility_defaults",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_project_class_visibility_defaults_project_id",
        "project_class_visibility_defaults",
        ["project_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_project_class_visibility_defaults_project_id",
        table_name="project_class_visibility_defaults",
    )
    op.drop_index(
        "ix_project_class_visibility_defaults_project",
        table_name="project_class_visibility_defaults",
    )
    op.drop_table("project_class_visibility_defaults")

    op.drop_index(
        "ix_class_visibility_preferences_project_user",
        table_name="class_visibility_preferences",
    )
    op.drop_index(
        "ix_class_visibility_preferences_project_id",
        table_name="class_visibility_preferences",
    )
    op.drop_table("class_visibility_preferences")
