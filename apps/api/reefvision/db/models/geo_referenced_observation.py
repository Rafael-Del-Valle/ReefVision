"""Persisted geo-referenced video observations."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now

if TYPE_CHECKING:
    from reefvision.db.models.project import Project
    from reefvision.db.models.video_asset import VideoAsset
    from reefvision.db.models.video_track import VideoTrack


class GeoReferencedObservation(Base):
    """Immutable geographic result produced from one video observation.

    Query-critical fields are stored as scalar columns. ``payload_json`` keeps
    the complete Task 10 GeoReferencedObservation contract so calibration,
    telemetry, pose, uncertainty, and method provenance remain reproducible.
    """

    __tablename__ = "geo_referenced_observations"

    __table_args__ = (
        Index(
            "ix_geo_referenced_observations_project_created",
            "project_id",
            "created_at",
        ),
        Index(
            "ix_geo_referenced_observations_video_frame",
            "video_id",
            "frame_index",
        ),
        Index(
            "ix_geo_referenced_observations_track_frame",
            "track_id",
            "frame_index",
        ),
        Index(
            "ix_geo_referenced_observations_video_stale",
            "video_id",
            "is_stale",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )

    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )

    video_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=False,
    )

    track_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("video_tracks.id", ondelete="SET NULL"),
        nullable=True,
    )

    # There is not yet a persisted detection table to reference directly.
    detection_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    schema_version: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
    )

    frame_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    frame_width_px: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    frame_height_px: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    bbox_x_min: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    bbox_y_min: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    bbox_x_max: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    bbox_y_max: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    representative_pixel_x: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    representative_pixel_y: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    representative_pixel_method: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
    )

    frame_time_s: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    latitude_deg: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    longitude_deg: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    crs: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="EPSG:4326",
    )

    method_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    method_version: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    calibration_id: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    calibration_version: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    calibration_checksum_sha256: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    telemetry_source_id: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
    )

    telemetry_source_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    telemetry_sample_index: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    signed_time_delta_ms: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    uncertainty_available: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    configuration_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    is_stale: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    stale_reason: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    stale_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    project: Mapped[Project] = relationship(
        back_populates="geo_referenced_observations",
    )

    video: Mapped[VideoAsset] = relationship(
        back_populates="geo_referenced_observations",
    )

    track: Mapped[VideoTrack | None] = relationship(
        back_populates="geo_referenced_observations",
    )
