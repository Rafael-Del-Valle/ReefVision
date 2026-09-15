"""Generate editable polygon geometry without modifying annotations or assets."""

from math import floor

from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.domain.errors import NotFoundError
from reefvision.repositories.images import ImageRepository
from reefvision.schemas.annotations import PolygonPoint
from reefvision.schemas.polygon_fill import (
    PolygonFillRequest,
    PolygonFillResponse,
    SmartCloseRequest,
)
from reefvision.storage.raster_edits import (
    polygon_fill_from_managed_image,
    smart_close_polygon_from_managed_image,
)


def generate_polygon_fill(
    session: Session, settings: Settings, image_id: str, payload: PolygonFillRequest
) -> PolygonFillResponse:
    image = ImageRepository(session).get(image_id)
    if image is None:
        raise NotFoundError("Image not found")
    points = polygon_fill_from_managed_image(
        settings,
        source_path=image.managed_path,
        expected_size=(image.width_px, image.height_px),
        seed_x=floor(payload.seed.x),
        seed_y=floor(payload.seed.y),
        tolerance=payload.tolerance,
    )
    return PolygonFillResponse(points=[PolygonPoint(x=x, y=y) for x, y in points])



def generate_smart_close_polygon(
    session: Session, settings: Settings, image_id: str, payload: SmartCloseRequest
) -> PolygonFillResponse:
    image = ImageRepository(session).get(image_id)
    if image is None:
        raise NotFoundError("Image not found")
    points = smart_close_polygon_from_managed_image(
        settings,
        source_path=image.managed_path,
        expected_size=(image.width_px, image.height_px),
        seed_x=floor(payload.seed.x),
        seed_y=floor(payload.seed.y),
        closure_strength=payload.closure_strength,
    )
    return PolygonFillResponse(points=[PolygonPoint(x=x, y=y) for x, y in points])
