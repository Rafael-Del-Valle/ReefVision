"""Persist learned ReefPose temporal datasets, runs and frame evidence."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b13_temporal_0001"
down_revision: str | None = "b13_scientific_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "temporal_reefpose_datasets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_temporal_reefpose_datasets_project_id", "temporal_reefpose_datasets", ["project_id"]
    )
    op.create_table(
        "temporal_reefpose_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "dataset_id",
            sa.String(36),
            sa.ForeignKey("temporal_reefpose_datasets.id", ondelete="CASCADE"),
        ),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="SET NULL")),
        sa.Column(
            "identity_run_id",
            sa.String(36),
            sa.ForeignKey("pose_identity_association_runs.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "identity_id",
            sa.String(36),
            sa.ForeignKey("pose_animal_identities.id", ondelete="SET NULL"),
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("configuration_json", sa.JSON(), nullable=False),
        sa.Column("input_manifest_json", sa.JSON(), nullable=False),
        sa.Column("input_manifest_sha256", sa.String(64), nullable=False),
        sa.Column("result_json", sa.JSON()),
        sa.Column("review_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_temporal_reefpose_runs_project_id", "temporal_reefpose_runs", ["project_id"]
    )
    op.create_table(
        "temporal_reefpose_frames",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("temporal_reefpose_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("frame_index", sa.Integer(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column("review_source", sa.String(20)),
        sa.UniqueConstraint("run_id", "frame_index", name="uq_temporal_reefpose_run_frame"),
    )
    op.create_index("ix_temporal_reefpose_frames_run_id", "temporal_reefpose_frames", ["run_id"])


def downgrade() -> None:
    op.drop_table("temporal_reefpose_frames")
    op.drop_table("temporal_reefpose_runs")
    op.drop_table("temporal_reefpose_datasets")
