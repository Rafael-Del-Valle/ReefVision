"""Add pose-specific active-learning rounds and candidates.

Revision ID: 0036
Revises: 0035
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pose_active_learning_rounds",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("video_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("selection_unit", sa.String(length=20), nullable=False),
        sa.Column("requested_size", sa.Integer(), nullable=False),
        sa.Column("selected_count", sa.Integer(), nullable=False),
        sa.Column("clip_radius_frames", sa.Integer(), nullable=False),
        sa.Column("minimum_frame_spacing", sa.Integer(), nullable=False),
        sa.Column("model_ids_json", sa.JSON(), nullable=False),
        sa.Column("scoring_config_json", sa.JSON(), nullable=False),
        sa.Column("selection_manifest_json", sa.JSON(), nullable=False),
        sa.Column("selection_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["video_id"],
            ["videos.id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "requested_size >= 1",
            name="ck_pose_al_round_requested_size",
        ),
        sa.CheckConstraint(
            "selected_count >= 1",
            name="ck_pose_al_round_selected_count",
        ),
        sa.CheckConstraint(
            "clip_radius_frames >= 0",
            name="ck_pose_al_round_clip_radius",
        ),
        sa.CheckConstraint(
            "minimum_frame_spacing >= 0",
            name="ck_pose_al_round_spacing",
        ),
        sa.UniqueConstraint(
            "project_id",
            "selection_sha256",
            name="uq_pose_al_round_selection",
        ),
    )
    op.create_index(
        "ix_pose_al_rounds_project_created",
        "pose_active_learning_rounds",
        ["project_id", "created_at"],
    )
    op.create_index(
        "ix_pose_al_rounds_video_created",
        "pose_active_learning_rounds",
        ["video_id", "created_at"],
    )
    op.create_index(
        "ix_pose_al_rounds_status",
        "pose_active_learning_rounds",
        ["status", "created_at"],
    )

    op.create_table(
        "pose_active_learning_candidates",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("round_id", sa.String(length=36), nullable=False),
        sa.Column("video_track_id", sa.String(length=36), nullable=False),
        sa.Column("focus_frame", sa.Integer(), nullable=False),
        sa.Column("frame_start", sa.Integer(), nullable=False),
        sa.Column("frame_end", sa.Integer(), nullable=False),
        sa.Column("acquisition_score", sa.Float(), nullable=False),
        sa.Column("score_components_json", sa.JSON(), nullable=False),
        sa.Column("reason_codes_json", sa.JSON(), nullable=False),
        sa.Column("pose_schema_id", sa.String(length=200), nullable=False),
        sa.Column("pose_schema_revision", sa.Integer(), nullable=False),
        sa.Column("source_track_revision", sa.Integer(), nullable=False),
        sa.Column("source_model_ids_json", sa.JSON(), nullable=False),
        sa.Column("source_job_ids_json", sa.JSON(), nullable=False),
        sa.Column("provenance_json", sa.JSON(), nullable=False),
        sa.Column("provenance_sha256", sa.String(length=64), nullable=False),
        sa.Column("review_status", sa.String(length=30), nullable=False),
        sa.Column("review_started_track_revision", sa.Integer(), nullable=True),
        sa.Column("verified_track_revision", sa.Integer(), nullable=True),
        sa.Column("verified_pose_sha256", sa.String(length=64), nullable=True),
        sa.Column("correction_id", sa.String(length=36), nullable=True),
        sa.Column("reviewed_by", sa.String(length=100), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["round_id"],
            ["pose_active_learning_rounds.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["video_track_id"],
            ["video_tracks.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["correction_id"],
            ["pose_landmark_corrections.id"],
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "focus_frame >= 0",
            name="ck_pose_al_candidate_focus_frame",
        ),
        sa.CheckConstraint(
            "frame_start >= 0",
            name="ck_pose_al_candidate_start_frame",
        ),
        sa.CheckConstraint(
            "frame_end >= frame_start",
            name="ck_pose_al_candidate_frame_order",
        ),
        sa.CheckConstraint(
            "focus_frame >= frame_start AND focus_frame <= frame_end",
            name="ck_pose_al_candidate_focus_in_window",
        ),
        sa.CheckConstraint(
            "acquisition_score >= 0 AND acquisition_score <= 1",
            name="ck_pose_al_candidate_score",
        ),
        sa.CheckConstraint(
            "pose_schema_revision >= 1",
            name="ck_pose_al_candidate_schema_revision",
        ),
        sa.CheckConstraint(
            "source_track_revision >= 1",
            name="ck_pose_al_candidate_track_revision",
        ),
        sa.UniqueConstraint(
            "round_id",
            "video_track_id",
            "focus_frame",
            name="uq_pose_al_candidate_round_track_frame",
        ),
    )
    op.create_index(
        "ix_pose_al_candidates_round_score",
        "pose_active_learning_candidates",
        ["round_id", "acquisition_score"],
    )
    op.create_index(
        "ix_pose_al_candidates_track_frame",
        "pose_active_learning_candidates",
        ["video_track_id", "focus_frame"],
    )
    op.create_index(
        "ix_pose_al_candidates_review",
        "pose_active_learning_candidates",
        ["review_status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pose_al_candidates_review",
        table_name="pose_active_learning_candidates",
    )
    op.drop_index(
        "ix_pose_al_candidates_track_frame",
        table_name="pose_active_learning_candidates",
    )
    op.drop_index(
        "ix_pose_al_candidates_round_score",
        table_name="pose_active_learning_candidates",
    )
    op.drop_table("pose_active_learning_candidates")

    op.drop_index(
        "ix_pose_al_rounds_status",
        table_name="pose_active_learning_rounds",
    )
    op.drop_index(
        "ix_pose_al_rounds_video_created",
        table_name="pose_active_learning_rounds",
    )
    op.drop_index(
        "ix_pose_al_rounds_project_created",
        table_name="pose_active_learning_rounds",
    )
    op.drop_table("pose_active_learning_rounds")
