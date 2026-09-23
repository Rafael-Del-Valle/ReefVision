"""Add persisted geo-referenced video observations.

Revision ID: 0027
Revises: 0026
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "geo_referenced_observations",
        sa.Column(
            "id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column(
            "video_id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column(
            "track_id",
            sa.String(length=36),
            nullable=True,
        ),
        sa.Column(
            "detection_id",
            sa.String(length=36),
            nullable=True,
        ),
        sa.Column(
            "schema_version",
            sa.String(length=40),
            nullable=False,
        ),
        sa.Column(
            "frame_index",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "frame_width_px",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "frame_height_px",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "bbox_x_min",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "bbox_y_min",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "bbox_x_max",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "bbox_y_max",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "representative_pixel_x",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "representative_pixel_y",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "representative_pixel_method",
            sa.String(length=40),
            nullable=False,
        ),
        sa.Column(
            "frame_time_s",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "latitude_deg",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "longitude_deg",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "crs",
            sa.String(length=40),
            nullable=False,
        ),
        sa.Column(
            "method_name",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "method_version",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "calibration_id",
            sa.String(length=200),
            nullable=False,
        ),
        sa.Column(
            "calibration_version",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "calibration_checksum_sha256",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "telemetry_source_id",
            sa.String(length=1000),
            nullable=False,
        ),
        sa.Column(
            "telemetry_source_type",
            sa.String(length=50),
            nullable=False,
        ),
        sa.Column(
            "telemetry_sample_index",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "signed_time_delta_ms",
            sa.Float(),
            nullable=True,
        ),
        sa.Column(
            "uncertainty_available",
            sa.Boolean(),
            nullable=False,
        ),
        sa.Column(
            "payload_json",
            sa.JSON(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(
            ["track_id"],
            ["video_tracks.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_geo_referenced_observations_project_created",
        "geo_referenced_observations",
        ["project_id", "created_at"],
        unique=False,
    )

    op.create_index(
        "ix_geo_referenced_observations_video_frame",
        "geo_referenced_observations",
        ["video_id", "frame_index"],
        unique=False,
    )

    op.create_index(
        "ix_geo_referenced_observations_track_frame",
        "geo_referenced_observations",
        ["track_id", "frame_index"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_geo_referenced_observations_track_frame",
        table_name="geo_referenced_observations",
    )

    op.drop_index(
        "ix_geo_referenced_observations_video_frame",
        table_name="geo_referenced_observations",
    )

    op.drop_index(
        "ix_geo_referenced_observations_project_created",
        table_name="geo_referenced_observations",
    )

    op.drop_table("geo_referenced_observations")
