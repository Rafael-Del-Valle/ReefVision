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
    created_at: datetime


class GeoReferencedObservationListResponse(BaseModel):
    """Collection response for geographic observation queries."""

    items: list[GeoReferencedObservationSummaryResponse]
    count: int = Field(ge=0)
