"""Add anatomical measurement and biological event runs.

Revision ID: 0042
Revises: 0041
"""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table("pose_measurement_runs",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("project_id", sa.String(36), nullable=False), sa.Column("video_id", sa.String(36), nullable=False),
        sa.Column("source_identity_run_id", sa.String(36), nullable=False), sa.Column("source_identity_run_revision", sa.Integer(), nullable=False), sa.Column("source_job_id", sa.String(36)),
        sa.Column("pose_schema_id", sa.String(200), nullable=False), sa.Column("pose_schema_revision", sa.Integer(), nullable=False), sa.Column("pose_schema_content_hash", sa.String(64), nullable=False),
        sa.Column("video_sha256", sa.String(64), nullable=False), sa.Column("video_revision", sa.Integer(), nullable=False), sa.Column("calibration_json", sa.JSON()), sa.Column("calibration_sha256", sa.String(64)),
        sa.Column("timebase_json", sa.JSON(), nullable=False), sa.Column("definitions_json", sa.JSON(), nullable=False), sa.Column("configuration_json", sa.JSON(), nullable=False),
        sa.Column("input_manifest_json", sa.JSON(), nullable=False), sa.Column("input_manifest_sha256", sa.String(64), nullable=False), sa.Column("status", sa.String(30), nullable=False),
        sa.Column("progress_json", sa.JSON(), nullable=False), sa.Column("error_json", sa.JSON()), sa.Column("provenance_json", sa.JSON(), nullable=False), sa.Column("result_sha256", sa.String(64)),
        sa.Column("verification_state", sa.String(30), nullable=False), sa.Column("revision", sa.Integer(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("source_identity_run_revision >= 1", name="ck_pose_measurement_identity_revision"), sa.CheckConstraint("revision >= 1", name="ck_pose_measurement_revision"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_identity_run_id"], ["pose_identity_association_runs.id"], ondelete="RESTRICT"), sa.ForeignKeyConstraint(["source_job_id"], ["jobs.id"], ondelete="SET NULL"))
    op.create_index("ix_pose_measurement_run_video_created", "pose_measurement_runs", ["video_id", "created_at"])
    op.create_index("ix_pose_measurement_run_status", "pose_measurement_runs", ["project_id", "status"])
    op.create_table("pose_measurement_series",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("measurement_run_id", sa.String(36), nullable=False), sa.Column("animal_identity_id", sa.String(36), nullable=False),
        sa.Column("definition_id", sa.String(100), nullable=False), sa.Column("measurement_kind", sa.String(50), nullable=False), sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("landmark_ids_json", sa.JSON(), nullable=False), sa.Column("formula_version", sa.String(50), nullable=False), sa.Column("unit_dimension", sa.String(30), nullable=False),
        sa.Column("pixel_unit", sa.String(30), nullable=False), sa.Column("physical_unit", sa.String(30)), sa.Column("summary_json", sa.JSON(), nullable=False), sa.Column("series_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.ForeignKeyConstraint(["measurement_run_id"], ["pose_measurement_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["animal_identity_id"], ["pose_animal_identities.id"], ondelete="RESTRICT"), sa.UniqueConstraint("measurement_run_id", "animal_identity_id", "definition_id", name="uq_pose_measurement_series_definition"))
    op.create_index("ix_pose_measurement_series_run_identity", "pose_measurement_series", ["measurement_run_id", "animal_identity_id"])
    op.create_table("pose_measurement_samples",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("series_id", sa.String(36), nullable=False), sa.Column("frame_index", sa.Integer(), nullable=False), sa.Column("time_s", sa.Float(), nullable=False),
        sa.Column("pixel_value", sa.Float()), sa.Column("physical_value", sa.Float()), sa.Column("value_json", sa.JSON(), nullable=False), sa.Column("confidence", sa.Float()), sa.Column("valid", sa.Boolean(), nullable=False),
        sa.Column("quality_flags_json", sa.JSON(), nullable=False), sa.Column("source_observation_ids_json", sa.JSON(), nullable=False), sa.Column("source_observation_revisions_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["series_id"], ["pose_measurement_series.id"], ondelete="CASCADE"), sa.UniqueConstraint("series_id", "frame_index", name="uq_pose_measurement_sample_frame"))
    op.create_index("ix_pose_measurement_sample_series_time", "pose_measurement_samples", ["series_id", "time_s"])
    op.create_table("pose_event_detection_runs",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("measurement_run_id", sa.String(36), nullable=False), sa.Column("source_job_id", sa.String(36)),
        sa.Column("configuration_json", sa.JSON(), nullable=False), sa.Column("configuration_sha256", sa.String(64), nullable=False), sa.Column("status", sa.String(30), nullable=False),
        sa.Column("progress_json", sa.JSON(), nullable=False), sa.Column("error_json", sa.JSON()), sa.Column("provenance_json", sa.JSON(), nullable=False), sa.Column("result_sha256", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["measurement_run_id"], ["pose_measurement_runs.id"], ondelete="RESTRICT"), sa.ForeignKeyConstraint(["source_job_id"], ["jobs.id"], ondelete="SET NULL"))
    op.create_index("ix_pose_event_detection_measurement", "pose_event_detection_runs", ["measurement_run_id", "created_at"])
    op.create_table("pose_biological_event_revisions",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("event_series_id", sa.String(36), nullable=False), sa.Column("revision", sa.Integer(), nullable=False), sa.Column("supersedes_event_id", sa.String(36)),
        sa.Column("event_detection_run_id", sa.String(36), nullable=False), sa.Column("measurement_series_id", sa.String(36), nullable=False), sa.Column("animal_identity_id", sa.String(36), nullable=False),
        sa.Column("start_frame", sa.Integer(), nullable=False), sa.Column("peak_frame", sa.Integer()), sa.Column("end_frame", sa.Integer()), sa.Column("start_time_s", sa.Float(), nullable=False), sa.Column("peak_time_s", sa.Float()), sa.Column("end_time_s", sa.Float()),
        sa.Column("baseline_value", sa.Float()), sa.Column("peak_value", sa.Float()), sa.Column("amplitude", sa.Float()), sa.Column("duration_s", sa.Float()), sa.Column("confidence", sa.Float()),
        sa.Column("cycle_state", sa.String(30), nullable=False), sa.Column("detection_source", sa.String(30), nullable=False), sa.Column("review_state", sa.String(30), nullable=False), sa.Column("rejection_reasons_json", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text()), sa.Column("actor", sa.String(100), nullable=False), sa.Column("before_sha256", sa.String(64)), sa.Column("after_sha256", sa.String(64), nullable=False), sa.Column("is_current", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision >= 1", name="ck_pose_biological_event_revision"), sa.ForeignKeyConstraint(["supersedes_event_id"], ["pose_biological_event_revisions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["event_detection_run_id"], ["pose_event_detection_runs.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["measurement_series_id"], ["pose_measurement_series.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["animal_identity_id"], ["pose_animal_identities.id"], ondelete="RESTRICT"), sa.UniqueConstraint("event_series_id", "revision", name="uq_pose_biological_event_revision"))
    op.create_index("ix_pose_biological_event_current", "pose_biological_event_revisions", ["event_detection_run_id", "is_current"])


def downgrade() -> None:
    op.drop_index("ix_pose_biological_event_current", table_name="pose_biological_event_revisions"); op.drop_table("pose_biological_event_revisions")
    op.drop_index("ix_pose_event_detection_measurement", table_name="pose_event_detection_runs"); op.drop_table("pose_event_detection_runs")
    op.drop_index("ix_pose_measurement_sample_series_time", table_name="pose_measurement_samples"); op.drop_table("pose_measurement_samples")
    op.drop_index("ix_pose_measurement_series_run_identity", table_name="pose_measurement_series"); op.drop_table("pose_measurement_series")
    op.drop_index("ix_pose_measurement_run_status", table_name="pose_measurement_runs"); op.drop_index("ix_pose_measurement_run_video_created", table_name="pose_measurement_runs"); op.drop_table("pose_measurement_runs")
