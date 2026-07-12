"""Add projects and label classes.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=220), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("storage_root", sa.String(length=500), nullable=False),
        sa.Column("default_annotation_type", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
        sa.UniqueConstraint("storage_root"),
    )
    op.create_index(op.f("ix_projects_slug"), "projects", ["slug"], unique=True)
    op.create_table(
        "label_classes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("class_index", sa.Integer(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("scientific_name", sa.String(length=200), nullable=True),
        sa.Column("state_name", sa.String(length=100), nullable=True),
        sa.Column("display_color", sa.String(length=7), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "class_index", name="uq_label_classes_project_index"),
        sa.UniqueConstraint("project_id", "name", name="uq_label_classes_project_name"),
    )
    op.create_index(
        op.f("ix_label_classes_project_id"), "label_classes", ["project_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_label_classes_project_id"), table_name="label_classes")
    op.drop_table("label_classes")
    op.drop_index(op.f("ix_projects_slug"), table_name="projects")
    op.drop_table("projects")
