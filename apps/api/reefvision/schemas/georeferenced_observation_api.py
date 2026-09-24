"""API response schemas for persisted geo-referenced observations."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from reefvision.schemas.georeferenced_observation import (
    BoundingBoxPixels,
    GeographicLocation,
    RepresentativePixel,
)


class GeoReferencedObservationSummaryResponse(BaseModel):
    """Map- and timeline-friendly persisted observation summary."""

    id: UUID
    project_id: UUID
    video_asset_id: UUID
    track_id: UUID | None = None
    detection_id: UUID | None = None

    frame_index: int
    frame_width_px: int
    frame_height_px: int
    frame_time_s: float

    bbox: BoundingBoxPixels
    representative_pixel: RepresentativePixel
    location: GeographicLocation

    uncertainty_available: bool
    method_version: str

    configuration_hash: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    is_stale: bool
    stale_reason: str | None = None
    stale_at: datetime | None = None

    created_at: datetime


class GeoReferencedObservationListResponse(BaseModel):
    """Collection response for geographic observation queries."""

    items: list[GeoReferencedObservationSummaryResponse]
    count: int = Field(ge=0)


class GeoReferencedObservationRecomputeReplacement(BaseModel):
    """One immutable stale observation replaced by a fresh derivation."""

    old_observation_id: UUID
    new_observation_id: UUID
    frame_index: int = Field(ge=0)
    track_id: UUID | None = None


class GeoReferencedObservationRecomputeResponse(BaseModel):
    """Result of one atomic video-level georeferencing recomputation."""

    video_id: UUID
    configuration_hash: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )

    invalidated_count: int = Field(ge=0)
    stale_count: int = Field(ge=0)
    recomputed_count: int = Field(ge=0)
    unchanged_count: int = Field(ge=0)

    replacements: list[GeoReferencedObservationRecomputeReplacement]
