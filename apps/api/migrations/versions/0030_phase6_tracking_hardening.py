"""Harden Phase 6 track corrections, zones, analysis, and evaluation.

Revision ID: 0030
Revises: 0029
Create Date: 2026-07-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("videos") as batch_op:
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
        )
        batch_op.add_column(
            sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1"))
        )

    with op.batch_alter_table("video_tracks") as batch_op:
        batch_op.add_column(sa.Column("origin_job_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("name", sa.String(length=200), nullable=True))
        batch_op.add_column(
            sa.Column(
                "source_type",
                sa.String(length=30),
                nullable=False,
                server_default=sa.text("'human'"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "is_ground_truth",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "created_by",
                sa.String(length=100),
                nullable=False,
                server_default=sa.text("'local_user'"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "updated_by",
                sa.String(length=100),
                nullable=False,
                server_default=sa.text("'local_user'"),
            )
        )
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(
            sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1"))
        )
        batch_op.create_foreign_key(
            "fk_video_tracks_origin_job_id_jobs",
            "jobs",
            ["origin_job_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_video_tracks_origin_job_id", ["origin_job_id"])

    op.create_table(
        "video_zones",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("video_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("x_min", sa.Float(), nullable=False),
        sa.Column("y_min", sa.Float(), nullable=False),
        sa.Column("x_max", sa.Float(), nullable=False),
        sa.Column("y_max", sa.Float(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_video_zones_video_id", "video_zones", ["video_id"])
    op.create_index(
        "ix_video_zones_video_deleted",
        "video_zones",
        ["video_id", "deleted_at"],
    )

    op.create_table(
        "video_track_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("video_track_id", sa.String(length=36), nullable=False),
        sa.Column("video_id", sa.String(length=36), nullable=False),
        sa.Column("operation_id", sa.String(length=100), nullable=True),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("before_json", sa.JSON(), nullable=True),
        sa.Column("after_json", sa.JSON(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("actor", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["video_track_id"], ["video_tracks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("operation_id", name="uq_video_track_events_operation_id"),
    )
    op.create_index("ix_video_track_events_video_id", "video_track_events", ["video_id"])
    op.create_index(
        "ix_video_track_events_track_created",
        "video_track_events",
        ["video_track_id", "created_at"],
    )
    op.create_index(
        "ix_video_track_events_video_created",
        "video_track_events",
        ["video_id", "created_at"],
    )

    op.create_table(
        "video_analysis_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("video_id", sa.String(length=36), nullable=False),
        sa.Column("configuration_json", sa.JSON(), nullable=False),
        sa.Column("source_revisions_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("result_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_video_analysis_runs_video_id", "video_analysis_runs", ["video_id"])
    op.create_index(
        "ix_video_analysis_runs_video_created",
        "video_analysis_runs",
        ["video_id", "created_at"],
    )
    op.create_index(
        "ix_video_analysis_runs_checksum",
        "video_analysis_runs",
        ["result_sha256"],
    )

    op.create_table(
        "video_tracking_evaluations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("video_id", sa.String(length=36), nullable=False),
        sa.Column("configuration_json", sa.JSON(), nullable=False),
        sa.Column("reference_track_ids_json", sa.JSON(), nullable=False),
        sa.Column("candidate_job_ids_json", sa.JSON(), nullable=False),
        sa.Column("source_revisions_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("result_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_video_tracking_evaluations_video_id",
        "video_tracking_evaluations",
        ["video_id"],
    )
    op.create_index(
        "ix_video_tracking_evaluations_video_created",
        "video_tracking_evaluations",
        ["video_id", "created_at"],
    )
    op.create_index(
        "ix_video_tracking_evaluations_checksum",
        "video_tracking_evaluations",
        ["result_sha256"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_video_tracking_evaluations_checksum",
        table_name="video_tracking_evaluations",
    )
    op.drop_index(
        "ix_video_tracking_evaluations_video_created",
        table_name="video_tracking_evaluations",
    )
    op.drop_index(
        "ix_video_tracking_evaluations_video_id",
        table_name="video_tracking_evaluations",
    )
    op.drop_table("video_tracking_evaluations")

    op.drop_index("ix_video_analysis_runs_checksum", table_name="video_analysis_runs")
    op.drop_index("ix_video_analysis_runs_video_created", table_name="video_analysis_runs")
    op.drop_index("ix_video_analysis_runs_video_id", table_name="video_analysis_runs")
    op.drop_table("video_analysis_runs")

    op.drop_index("ix_video_track_events_video_created", table_name="video_track_events")
    op.drop_index("ix_video_track_events_track_created", table_name="video_track_events")
    op.drop_index("ix_video_track_events_video_id", table_name="video_track_events")
    op.drop_table("video_track_events")

    op.drop_index("ix_video_zones_video_deleted", table_name="video_zones")
    op.drop_index("ix_video_zones_video_id", table_name="video_zones")
    op.drop_table("video_zones")

    with op.batch_alter_table("video_tracks") as batch_op:
        batch_op.drop_index("ix_video_tracks_origin_job_id")
        batch_op.drop_constraint("fk_video_tracks_origin_job_id_jobs", type_="foreignkey")
        batch_op.drop_column("revision")
        batch_op.drop_column("deleted_at")
        batch_op.drop_column("updated_by")
        batch_op.drop_column("created_by")
        batch_op.drop_column("is_ground_truth")
        batch_op.drop_column("source_type")
        batch_op.drop_column("name")
        batch_op.drop_column("origin_job_id")

    with op.batch_alter_table("videos") as batch_op:
        batch_op.drop_column("revision")
        batch_op.drop_column("updated_at")
