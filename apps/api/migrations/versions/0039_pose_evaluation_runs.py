"""Add immutable scientific pose evaluation runs.

Revision ID: 0039
Revises: 0038
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pose_evaluation_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("model_id", sa.String(length=36), nullable=False),
        sa.Column("evaluation_dataset_id", sa.String(length=36), nullable=False),
        sa.Column("schema_version", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("configuration_json", sa.JSON(), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("predictions_json", sa.JSON(), nullable=False),
        sa.Column("provenance_json", sa.JSON(), nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.Column("result_sha256", sa.String(length=64), nullable=False),
        sa.Column("inference_latency_ms", sa.Float(), nullable=False),
        sa.Column("images_per_second", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["evaluation_dataset_id"], ["pose_training_datasets.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["model_id"], ["model_registrations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pose_evaluation_runs_result_sha256",
        "pose_evaluation_runs",
        ["result_sha256"],
    )
    op.create_index(
        "ix_pose_evaluation_project_created",
        "pose_evaluation_runs",
        ["project_id", "created_at"],
    )
    op.create_index(
        "ix_pose_evaluation_model_created",
        "pose_evaluation_runs",
        ["model_id", "created_at"],
    )
    op.create_index(
        "ix_pose_evaluation_dataset_created",
        "pose_evaluation_runs",
        ["evaluation_dataset_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_pose_evaluation_runs_result_sha256", table_name="pose_evaluation_runs")
    op.drop_index("ix_pose_evaluation_dataset_created", table_name="pose_evaluation_runs")
    op.drop_index("ix_pose_evaluation_model_created", table_name="pose_evaluation_runs")
    op.drop_index("ix_pose_evaluation_project_created", table_name="pose_evaluation_runs")
    op.drop_table("pose_evaluation_runs")
