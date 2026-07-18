"""Add reproducible active-learning rounds.

Revision ID: 0022
Revises: 0021
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "active_learning_rounds",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("dataset_version_id", sa.String(36), nullable=True),
        sa.Column("review_queue_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("strategy", sa.String(40), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("requested_size", sa.Integer(), nullable=False),
        sa.Column("selected_count", sa.Integer(), nullable=False),
        sa.Column("model_ids_json", sa.JSON(), nullable=False),
        sa.Column("strategy_config_json", sa.JSON(), nullable=False),
        sa.Column("selection_manifest_json", sa.JSON(), nullable=False),
        sa.Column("selection_sha256", sa.String(64), nullable=False),
        sa.Column("feedback_summary_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_versions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["review_queue_id"], ["review_queues.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "project_id", "selection_sha256", name="uq_active_learning_round_selection"
        ),
    )
    op.create_index(
        "ix_active_learning_rounds_project_created",
        "active_learning_rounds",
        ["project_id", "created_at"],
    )
    op.create_index(
        "ix_active_learning_rounds_status_created",
        "active_learning_rounds",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_active_learning_rounds_status_created", table_name="active_learning_rounds"
    )
    op.drop_index(
        "ix_active_learning_rounds_project_created", table_name="active_learning_rounds"
    )
    op.drop_table("active_learning_rounds")
