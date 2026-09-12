"""Read-only image fill geometry, persisted through the normal annotation save."""

from pydantic import BaseModel, Field

from reefvision.schemas.annotations import PolygonPoint


class PolygonFillRequest(BaseModel):
    seed: PolygonPoint
    tolerance: int = Field(default=24, ge=0, le=255)


class PolygonFillResponse(BaseModel):
    points: list[PolygonPoint]
