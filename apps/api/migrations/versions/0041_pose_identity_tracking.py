"""Add multi-animal pose identity tracking records.

Revision ID: 0041
Revises: 0040
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pose_identity_association_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("video_id", sa.String(36), nullable=False),
        sa.Column("source_model_id", sa.String(36), nullable=True),
        sa.Column("source_job_id", sa.String(36), nullable=True),
        sa.Column("pose_schema_id", sa.String(200), nullable=False),
        sa.Column("pose_schema_revision", sa.Integer(), nullable=False),
        sa.Column("pose_schema_content_hash", sa.String(64), nullable=False),
        sa.Column("algorithm", sa.String(100), nullable=False),
        sa.Column("algorithm_version", sa.String(50), nullable=False),
        sa.Column("parameters_json", sa.JSON(), nullable=False),
        sa.Column("parameters_sha256", sa.String(64), nullable=False),
        sa.Column("input_manifest_sha256", sa.String(64), nullable=False),
        sa.Column("source_coordinate_space", sa.String(30), nullable=False),
        sa.Column("source_width", sa.Integer(), nullable=False),
        sa.Column("source_height", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("progress_json", sa.JSON(), nullable=False),
        sa.Column("error_json", sa.JSON(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("pose_schema_revision >= 1", name="ck_pose_identity_runs_schema_rev"),
        sa.CheckConstraint("revision >= 1", name="ck_pose_identity_runs_revision"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_model_id"], ["model_registrations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["source_job_id"], ["jobs.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_pose_identity_runs_video_created",
        "pose_identity_association_runs",
        ["video_id", "created_at"],
    )
    op.create_index(
        "ix_pose_identity_runs_project_status",
        "pose_identity_association_runs",
        ["project_id", "status"],
    )

    op.create_table(
        "pose_animal_identities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("association_run_id", sa.String(36), nullable=False),
        sa.Column("stable_identity_key", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=True),
        sa.Column("origin", sa.String(30), nullable=False),
        sa.Column("verification_state", sa.String(30), nullable=False),
        sa.Column("lifecycle_state", sa.String(30), nullable=False),
        sa.Column("first_frame", sa.Integer(), nullable=False),
        sa.Column("last_frame", sa.Integer(), nullable=True),
        sa.Column("mean_association_confidence", sa.Float(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("first_frame >= 0", name="ck_pose_animal_identity_first_frame"),
        sa.CheckConstraint(
            "last_frame IS NULL OR last_frame >= first_frame",
            name="ck_pose_animal_identity_frame_order",
        ),
        sa.ForeignKeyConstraint(
            ["association_run_id"], ["pose_identity_association_runs.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "association_run_id", "stable_identity_key", name="uq_pose_identity_key"
        ),
    )
    op.create_index(
        "ix_pose_animal_identity_run_frames",
        "pose_animal_identities",
        ["association_run_id", "first_frame"],
    )

    op.create_table(
        "pose_identity_observations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("observation_series_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("supersedes_observation_id", sa.String(36), nullable=True),
        sa.Column("association_run_id", sa.String(36), nullable=False),
        sa.Column("animal_identity_id", sa.String(36), nullable=True),
        sa.Column("source_video_track_id", sa.String(36), nullable=False),
        sa.Column("source_detection_key", sa.String(200), nullable=False),
        sa.Column("frame_index", sa.Integer(), nullable=False),
        sa.Column("time_s", sa.Float(), nullable=True),
        sa.Column("bbox_json", sa.JSON(), nullable=False),
        sa.Column("landmarks_json", sa.JSON(), nullable=False),
        sa.Column("detection_confidence", sa.Float(), nullable=True),
        sa.Column("association_confidence", sa.Float(), nullable=True),
        sa.Column("visibility_state", sa.String(30), nullable=False),
        sa.Column("assignment_source", sa.String(30), nullable=False),
        sa.Column("verification_state", sa.String(30), nullable=False),
        sa.Column("coordinate_space", sa.String(30), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("frame_index >= 0", name="ck_pose_identity_observation_frame"),
        sa.CheckConstraint("revision >= 1", name="ck_pose_identity_observation_rev"),
        sa.ForeignKeyConstraint(
            ["supersedes_observation_id"], ["pose_identity_observations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["association_run_id"], ["pose_identity_association_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["animal_identity_id"], ["pose_animal_identities.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_video_track_id"], ["video_tracks.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "observation_series_id", "revision", name="uq_pose_identity_observation_revision"
        ),
    )
    op.create_index(
        "ix_pose_identity_observation_run_frame",
        "pose_identity_observations",
        ["association_run_id", "frame_index"],
    )
    op.create_index(
        "ix_pose_identity_observation_identity_frame",
        "pose_identity_observations",
        ["animal_identity_id", "frame_index"],
    )

    op.create_table(
        "pose_identity_association_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("association_run_id", sa.String(36), nullable=False),
        sa.Column("observation_id", sa.String(36), nullable=False),
        sa.Column("candidate_identity_id", sa.String(36), nullable=True),
        sa.Column("previous_observation_id", sa.String(36), nullable=True),
        sa.Column("candidate_rank", sa.Integer(), nullable=False),
        sa.Column("selected", sa.Boolean(), nullable=False),
        sa.Column("passed_gate", sa.Boolean(), nullable=False),
        sa.Column("gate_reason", sa.String(100), nullable=True),
        sa.Column("total_cost", sa.Float(), nullable=False),
        sa.Column("acceptance_threshold", sa.Float(), nullable=False),
        sa.Column("score_components_json", sa.JSON(), nullable=False),
        sa.Column("association_confidence", sa.Float(), nullable=False),
        sa.Column("algorithm", sa.String(100), nullable=False),
        sa.Column("algorithm_version", sa.String(50), nullable=False),
        sa.Column("parameters_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("candidate_rank >= 1", name="ck_pose_identity_decision_rank"),
        sa.ForeignKeyConstraint(
            ["association_run_id"], ["pose_identity_association_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"], ["pose_identity_observations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["candidate_identity_id"], ["pose_animal_identities.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["previous_observation_id"], ["pose_identity_observations.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "observation_id", "candidate_rank", name="uq_pose_identity_decision_rank"
        ),
    )
    op.create_index(
        "ix_pose_identity_decision_run_selected",
        "pose_identity_association_decisions",
        ["association_run_id", "selected"],
    )

    op.create_table(
        "pose_identity_occlusions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("association_run_id", sa.String(36), nullable=False),
        sa.Column("animal_identity_id", sa.String(36), nullable=False),
        sa.Column("start_frame", sa.Integer(), nullable=False),
        sa.Column("end_frame", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(50), nullable=False),
        sa.Column("recovery_confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("start_frame >= 0", name="ck_pose_identity_occlusion_start"),
        sa.CheckConstraint(
            "end_frame IS NULL OR end_frame >= start_frame", name="ck_pose_identity_occlusion_order"
        ),
        sa.ForeignKeyConstraint(
            ["association_run_id"], ["pose_identity_association_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["animal_identity_id"], ["pose_animal_identities.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_pose_identity_occlusion_identity",
        "pose_identity_occlusions",
        ["animal_identity_id", "start_frame"],
    )

    op.create_table(
        "pose_identity_corrections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("association_run_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("target_type", sa.String(40), nullable=False),
        sa.Column("target_id", sa.String(100), nullable=False),
        sa.Column("frame_start", sa.Integer(), nullable=True),
        sa.Column("frame_end", sa.Integer(), nullable=True),
        sa.Column("before_json", sa.JSON(), nullable=False),
        sa.Column("after_json", sa.JSON(), nullable=False),
        sa.Column("before_sha256", sa.String(64), nullable=False),
        sa.Column("after_sha256", sa.String(64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision >= 1", name="ck_pose_identity_correction_revision"),
        sa.ForeignKeyConstraint(
            ["association_run_id"], ["pose_identity_association_runs.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_pose_identity_correction_run_created",
        "pose_identity_corrections",
        ["association_run_id", "created_at"],
    )

    op.create_table(
        "pose_identity_truth_datasets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("video_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("pose_schema_id", sa.String(200), nullable=False),
        sa.Column("pose_schema_revision", sa.Integer(), nullable=False),
        sa.Column("pose_schema_content_hash", sa.String(64), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("verification_state", sa.String(30), nullable=False),
        sa.Column("verified_by", sa.String(100), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_pose_identity_truth_video_created",
        "pose_identity_truth_datasets",
        ["video_id", "created_at"],
    )

    op.create_table(
        "pose_identity_evaluation_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("association_run_id", sa.String(36), nullable=False),
        sa.Column("association_run_revision", sa.Integer(), nullable=False),
        sa.Column("truth_dataset_id", sa.String(36), nullable=False),
        sa.Column("configuration_json", sa.JSON(), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.Column("provenance_json", sa.JSON(), nullable=False),
        sa.Column("result_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["association_run_id"], ["pose_identity_association_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["truth_dataset_id"], ["pose_identity_truth_datasets.id"], ondelete="RESTRICT"
        ),
    )
    op.create_index(
        "ix_pose_identity_eval_run_created",
        "pose_identity_evaluation_runs",
        ["association_run_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_pose_identity_eval_run_created", table_name="pose_identity_evaluation_runs")
    op.drop_table("pose_identity_evaluation_runs")
    op.drop_index("ix_pose_identity_truth_video_created", table_name="pose_identity_truth_datasets")
    op.drop_table("pose_identity_truth_datasets")
    op.drop_index("ix_pose_identity_correction_run_created", table_name="pose_identity_corrections")
    op.drop_table("pose_identity_corrections")
    op.drop_index("ix_pose_identity_occlusion_identity", table_name="pose_identity_occlusions")
    op.drop_table("pose_identity_occlusions")
    op.drop_index(
        "ix_pose_identity_decision_run_selected",
        table_name="pose_identity_association_decisions",
    )
    op.drop_table("pose_identity_association_decisions")
    op.drop_index(
        "ix_pose_identity_observation_identity_frame", table_name="pose_identity_observations"
    )
    op.drop_index("ix_pose_identity_observation_run_frame", table_name="pose_identity_observations")
    op.drop_table("pose_identity_observations")
    op.drop_index("ix_pose_animal_identity_run_frames", table_name="pose_animal_identities")
    op.drop_table("pose_animal_identities")
    op.drop_index(
        "ix_pose_identity_runs_project_status", table_name="pose_identity_association_runs"
    )
    op.drop_index(
        "ix_pose_identity_runs_video_created", table_name="pose_identity_association_runs"
    )
    op.drop_table("pose_identity_association_runs")
