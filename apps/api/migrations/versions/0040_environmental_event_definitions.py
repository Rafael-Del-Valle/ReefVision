"""Persist immutable researcher-defined environmental threshold queries.

Revision ID: 0040
Revises: 0039
"""

import sqlalchemy as sa
from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "environmental_event_definitions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("query_json", sa.JSON(), nullable=False),
        sa.Column("definition_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_environmental_event_definition_project",
        "environmental_event_definitions",
        ["project_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_environmental_event_definition_project",
        table_name="environmental_event_definitions",
    )
    op.drop_table("environmental_event_definitions")
