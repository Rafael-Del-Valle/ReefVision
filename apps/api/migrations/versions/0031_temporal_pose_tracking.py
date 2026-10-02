"""Add canonical temporal pose tracking persistence.

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pose_landmark_tracks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "parent_video_track_id",
            sa.String(length=36),
            sa.ForeignKey("video_tracks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("pose_schema_id", sa.String(length=200), nullable=False),
        sa.Column("pose_schema_revision", sa.Integer(), nullable=False),
        sa.Column("semantic_label", sa.String(length=100), nullable=False),
        sa.Column("lifecycle_state", sa.String(length=20), nullable=False),
        sa.Column("first_frame", sa.Integer(), nullable=False),
        sa.Column("last_frame", sa.Integer(), nullable=True),
        sa.Column("origin", sa.String(length=20), nullable=False),
        sa.Column(
            "source_model_id",
            sa.String(length=36),
            sa.ForeignKey("model_registrations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "source_job_id",
            sa.String(length=36),
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("association_algorithm", sa.String(length=100), nullable=True),
        sa.Column("association_algorithm_version", sa.String(length=100), nullable=True),
        sa.Column("association_parameters_json", sa.JSON(), nullable=False),
        sa.Column("association_parameters_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("terminated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "first_frame >= 0",
            name="ck_pose_landmark_tracks_first_frame",
        ),
        sa.CheckConstraint(
            "last_frame IS NULL OR last_frame >= first_frame",
            name="ck_pose_landmark_tracks_frame_order",
        ),
        sa.CheckConstraint(
            "pose_schema_revision >= 1",
            name="ck_pose_landmark_tracks_schema_revision",
        ),
    )
    op.create_index(
        "ix_pose_landmark_tracks_parent_label",
        "pose_landmark_tracks",
        ["parent_video_track_id", "semantic_label"],
    )
    op.create_index(
        "ix_pose_landmark_tracks_parent_frames",
        "pose_landmark_tracks",
        ["parent_video_track_id", "first_frame", "last_frame"],
    )

    op.create_table(
        "pose_landmark_observations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("observation_series_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "supersedes_observation_id",
            sa.String(length=36),
            sa.ForeignKey("pose_landmark_observations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "parent_video_track_id",
            sa.String(length=36),
            sa.ForeignKey("video_tracks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("frame_index", sa.Integer(), nullable=False),
        sa.Column("time_s", sa.Float(), nullable=True),
        sa.Column("pose_schema_id", sa.String(length=200), nullable=False),
        sa.Column("pose_schema_revision", sa.Integer(), nullable=False),
        sa.Column("semantic_label", sa.String(length=100), nullable=False),
        sa.Column("occurrence_index", sa.Integer(), nullable=False),
        sa.Column("observed_x_px", sa.Float(), nullable=True),
        sa.Column("observed_y_px", sa.Float(), nullable=True),
        sa.Column("predicted_x_px", sa.Float(), nullable=True),
        sa.Column("predicted_y_px", sa.Float(), nullable=True),
        sa.Column("landmark_confidence", sa.Float(), nullable=True),
        sa.Column("visibility_state", sa.String(length=30), nullable=False),
        sa.Column("observation_source", sa.String(length=20), nullable=False),
        sa.Column(
            "source_model_id",
            sa.String(length=36),
            sa.ForeignKey("model_registrations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "source_job_id",
            sa.String(length=36),
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_pose_landmark_observations_revision",
        ),
        sa.CheckConstraint(
            "frame_index >= 0",
            name="ck_pose_landmark_observations_frame",
        ),
        sa.CheckConstraint(
            "occurrence_index >= 0",
            name="ck_pose_landmark_observations_occurrence",
        ),
        sa.CheckConstraint(
            "landmark_confidence IS NULL OR "
            "(landmark_confidence >= 0 AND landmark_confidence <= 1)",
            name="ck_pose_landmark_observations_confidence",
        ),
        sa.CheckConstraint(
            "(observed_x_px IS NULL) = (observed_y_px IS NULL)",
            name="ck_pose_landmark_observations_observed_pair",
        ),
        sa.CheckConstraint(
            "(predicted_x_px IS NULL) = (predicted_y_px IS NULL)",
            name="ck_pose_landmark_observations_predicted_pair",
        ),
        sa.CheckConstraint(
            "visibility_state NOT IN ('occluded', 'out_of_frame', 'absent') "
            "OR (observed_x_px IS NULL AND observed_y_px IS NULL)",
            name="ck_pose_landmark_observations_missing_unobserved",
        ),
        sa.UniqueConstraint(
            "observation_series_id",
            "revision",
            name="uq_pose_landmark_observations_series_revision",
        ),
    )
    op.create_index(
        "ix_pose_landmark_observations_parent_frame",
        "pose_landmark_observations",
        ["parent_video_track_id", "frame_index"],
    )
    op.create_index(
        "ix_pose_landmark_observations_parent_label_frame",
        "pose_landmark_observations",
        ["parent_video_track_id", "semantic_label", "frame_index"],
    )

    op.create_table(
        "pose_landmark_association_decisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "observation_id",
            sa.String(length=36),
            sa.ForeignKey("pose_landmark_observations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("decision_revision", sa.Integer(), nullable=False),
        sa.Column(
            "supersedes_decision_id",
            sa.String(length=36),
            sa.ForeignKey("pose_landmark_association_decisions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "selected_landmark_track_id",
            sa.String(length=36),
            sa.ForeignKey("pose_landmark_tracks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "previous_observation_id",
            sa.String(length=36),
            sa.ForeignKey("pose_landmark_observations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("association_state", sa.String(length=30), nullable=False),
        sa.Column("association_confidence", sa.Float(), nullable=True),
        sa.Column("verification_state", sa.String(length=30), nullable=False),
        sa.Column("association_source", sa.String(length=20), nullable=False),
        sa.Column("candidate_margin", sa.Float(), nullable=True),
        sa.Column("total_cost", sa.Float(), nullable=True),
        sa.Column("cost_breakdown_json", sa.JSON(), nullable=True),
        sa.Column("algorithm", sa.String(length=100), nullable=True),
        sa.Column("algorithm_version", sa.String(length=100), nullable=True),
        sa.Column("parameters_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "decision_revision >= 1",
            name="ck_pose_landmark_associations_revision",
        ),
        sa.CheckConstraint(
            "association_confidence IS NULL OR "
            "(association_confidence >= 0 AND association_confidence <= 1)",
            name="ck_pose_landmark_associations_confidence",
        ),
        sa.CheckConstraint(
            "((association_state IN ('confirmed', 'provisional')) "
            "AND selected_landmark_track_id IS NOT NULL) OR "
            "((association_state IN ('unresolved', 'identity_break')) "
            "AND selected_landmark_track_id IS NULL)",
            name="ck_pose_landmark_associations_identity_state",
        ),
        sa.UniqueConstraint(
            "observation_id",
            "decision_revision",
            name="uq_pose_landmark_associations_observation_revision",
        ),
    )
    op.create_index(
        "ix_pose_landmark_associations_track",
        "pose_landmark_association_decisions",
        ["selected_landmark_track_id", "created_at"],
    )

    op.create_table(
        "pose_landmark_association_candidates",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "association_decision_id",
            sa.String(length=36),
            sa.ForeignKey("pose_landmark_association_decisions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_landmark_track_id",
            sa.String(length=36),
            sa.ForeignKey("pose_landmark_tracks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("total_cost", sa.Float(), nullable=False),
        sa.Column("normalized_confidence", sa.Float(), nullable=True),
        sa.Column("motion_cost", sa.Float(), nullable=True),
        sa.Column("geometry_cost", sa.Float(), nullable=True),
        sa.Column("appearance_cost", sa.Float(), nullable=True),
        sa.Column("ordering_cost", sa.Float(), nullable=True),
        sa.Column("shape_cost", sa.Float(), nullable=True),
        sa.CheckConstraint(
            "rank >= 1",
            name="ck_pose_landmark_candidates_rank",
        ),
        sa.CheckConstraint(
            "normalized_confidence IS NULL OR "
            "(normalized_confidence >= 0 AND normalized_confidence <= 1)",
            name="ck_pose_landmark_candidates_confidence",
        ),
        sa.UniqueConstraint(
            "association_decision_id",
            "rank",
            name="uq_pose_landmark_candidates_decision_rank",
        ),
    )
    op.create_index(
        "ix_pose_landmark_candidates_decision",
        "pose_landmark_association_candidates",
        ["association_decision_id"],
    )

    op.create_table(
        "pose_landmark_corrections",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "parent_video_track_id",
            sa.String(length=36),
            sa.ForeignKey("video_tracks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("target_type", sa.String(length=40), nullable=False),
        sa.Column("target_id", sa.String(length=100), nullable=False),
        sa.Column("frame_start", sa.Integer(), nullable=True),
        sa.Column("frame_end", sa.Integer(), nullable=True),
        sa.Column("reason_code", sa.String(length=100), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("before_json", sa.JSON(), nullable=False),
        sa.Column("after_json", sa.JSON(), nullable=False),
        sa.Column("actor", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "frame_start IS NULL OR frame_start >= 0",
            name="ck_pose_landmark_corrections_frame_start",
        ),
        sa.CheckConstraint(
            "frame_end IS NULL OR frame_end >= 0",
            name="ck_pose_landmark_corrections_frame_end",
        ),
        sa.CheckConstraint(
            "frame_start IS NULL OR frame_end IS NULL OR frame_end >= frame_start",
            name="ck_pose_landmark_corrections_frame_order",
        ),
    )
    op.create_index(
        "ix_pose_landmark_corrections_parent_created",
        "pose_landmark_corrections",
        ["parent_video_track_id", "created_at"],
    )

    op.create_table(
        "pose_landmark_identity_breaks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "parent_video_track_id",
            sa.String(length=36),
            sa.ForeignKey("video_tracks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "predecessor_landmark_track_id",
            sa.String(length=36),
            sa.ForeignKey("pose_landmark_tracks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "successor_landmark_track_id",
            sa.String(length=36),
            sa.ForeignKey("pose_landmark_tracks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("break_after_frame", sa.Integer(), nullable=False),
        sa.Column("successor_start_frame", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(length=50), nullable=False),
        sa.Column("decision_confidence", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("human_verified", sa.Boolean(), nullable=False),
        sa.Column(
            "correction_id",
            sa.String(length=36),
            sa.ForeignKey("pose_landmark_corrections.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "break_after_frame >= 0",
            name="ck_pose_landmark_identity_breaks_frame",
        ),
        sa.CheckConstraint(
            "successor_start_frame IS NULL OR successor_start_frame > break_after_frame",
            name="ck_pose_landmark_identity_breaks_successor_frame",
        ),
        sa.CheckConstraint(
            "decision_confidence IS NULL OR "
            "(decision_confidence >= 0 AND decision_confidence <= 1)",
            name="ck_pose_landmark_identity_breaks_confidence",
        ),
    )
    op.create_index(
        "ix_pose_landmark_identity_breaks_parent_frame",
        "pose_landmark_identity_breaks",
        ["parent_video_track_id", "break_after_frame"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pose_landmark_identity_breaks_parent_frame",
        table_name="pose_landmark_identity_breaks",
    )
    op.drop_table("pose_landmark_identity_breaks")
    op.drop_index(
        "ix_pose_landmark_corrections_parent_created",
        table_name="pose_landmark_corrections",
    )
    op.drop_table("pose_landmark_corrections")
    op.drop_index(
        "ix_pose_landmark_candidates_decision",
        table_name="pose_landmark_association_candidates",
    )
    op.drop_table("pose_landmark_association_candidates")
    op.drop_index(
        "ix_pose_landmark_associations_track",
        table_name="pose_landmark_association_decisions",
    )
    op.drop_table("pose_landmark_association_decisions")
    op.drop_index(
        "ix_pose_landmark_observations_parent_label_frame",
        table_name="pose_landmark_observations",
    )
    op.drop_index(
        "ix_pose_landmark_observations_parent_frame",
        table_name="pose_landmark_observations",
    )
    op.drop_table("pose_landmark_observations")
    op.drop_index(
        "ix_pose_landmark_tracks_parent_frames",
        table_name="pose_landmark_tracks",
    )
    op.drop_index(
        "ix_pose_landmark_tracks_parent_label",
        table_name="pose_landmark_tracks",
    )
    op.drop_table("pose_landmark_tracks")
