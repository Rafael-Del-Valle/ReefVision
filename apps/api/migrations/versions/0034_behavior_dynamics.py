"""Add revisioned behavior ethograms and track-level behavior bouts.

Revision ID: 0034
Revises: 0033
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "behavior_ethogram_revisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("ethogram_series_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("supersedes_revision_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("definition_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_revision_id"],
            ["behavior_ethogram_revisions.id"],
            ondelete="SET NULL",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_behavior_ethogram_revision"),
        sa.UniqueConstraint(
            "ethogram_series_id",
            "revision",
            name="uq_behavior_ethogram_series_revision",
        ),
    )
    op.create_index(
        "ix_behavior_ethogram_revisions_series",
        "behavior_ethogram_revisions",
        ["ethogram_series_id"],
    )
    op.create_index(
        "ix_behavior_ethogram_revisions_project",
        "behavior_ethogram_revisions",
        ["project_id"],
    )

    op.create_table(
        "behavior_state_definitions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("ethogram_revision_id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("channel", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["ethogram_revision_id"],
            ["behavior_ethogram_revisions.id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("sort_order >= 0", name="ck_behavior_state_sort_order"),
        sa.UniqueConstraint(
            "ethogram_revision_id",
            "code",
            name="uq_behavior_state_ethogram_code",
        ),
    )
    op.create_index(
        "ix_behavior_state_definitions_ethogram",
        "behavior_state_definitions",
        ["ethogram_revision_id"],
    )

    op.create_table(
        "behavior_bout_revisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("bout_series_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("supersedes_bout_id", sa.String(length=36), nullable=True),
        sa.Column("video_track_id", sa.String(length=36), nullable=False),
        sa.Column("ethogram_revision_id", sa.String(length=36), nullable=False),
        sa.Column("behavior_state_id", sa.String(length=36), nullable=False),
        sa.Column("start_frame", sa.Integer(), nullable=False),
        sa.Column("end_frame", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("review_status", sa.String(length=30), nullable=False),
        sa.Column("source_track_revision", sa.Integer(), nullable=False),
        sa.Column("source_model_id", sa.String(length=36), nullable=True),
        sa.Column("source_job_id", sa.String(length=36), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("revision_reason", sa.String(length=100), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["supersedes_bout_id"],
            ["behavior_bout_revisions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["video_track_id"],
            ["video_tracks.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ethogram_revision_id"],
            ["behavior_ethogram_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["behavior_state_id"],
            ["behavior_state_definitions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_model_id"],
            ["model_registrations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_job_id"],
            ["jobs.id"],
            ondelete="SET NULL",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_behavior_bout_revision"),
        sa.CheckConstraint("start_frame >= 0", name="ck_behavior_bout_start_frame"),
        sa.CheckConstraint(
            "end_frame >= start_frame",
            name="ck_behavior_bout_frame_order",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_behavior_bout_confidence",
        ),
        sa.CheckConstraint(
            "source_track_revision >= 1",
            name="ck_behavior_bout_track_revision",
        ),
        sa.UniqueConstraint(
            "bout_series_id",
            "revision",
            name="uq_behavior_bout_series_revision",
        ),
    )
    op.create_index(
        "ix_behavior_bout_revisions_series",
        "behavior_bout_revisions",
        ["bout_series_id"],
    )
    op.create_index(
        "ix_behavior_bout_revisions_track",
        "behavior_bout_revisions",
        ["video_track_id", "start_frame", "end_frame"],
    )
    op.create_index(
        "ix_behavior_bout_revisions_ethogram",
        "behavior_bout_revisions",
        ["ethogram_revision_id"],
    )
    op.create_index(
        "ix_behavior_bout_revisions_state",
        "behavior_bout_revisions",
        ["behavior_state_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_behavior_bout_revisions_state",
        table_name="behavior_bout_revisions",
    )
    op.drop_index(
        "ix_behavior_bout_revisions_ethogram",
        table_name="behavior_bout_revisions",
    )
    op.drop_index(
        "ix_behavior_bout_revisions_track",
        table_name="behavior_bout_revisions",
    )
    op.drop_index(
        "ix_behavior_bout_revisions_series",
        table_name="behavior_bout_revisions",
    )
    op.drop_table("behavior_bout_revisions")
    op.drop_index(
        "ix_behavior_state_definitions_ethogram",
        table_name="behavior_state_definitions",
    )
    op.drop_table("behavior_state_definitions")
    op.drop_index(
        "ix_behavior_ethogram_revisions_project",
        table_name="behavior_ethogram_revisions",
    )
    op.drop_index(
        "ix_behavior_ethogram_revisions_series",
        table_name="behavior_ethogram_revisions",
    )
    op.drop_table("behavior_ethogram_revisions")
