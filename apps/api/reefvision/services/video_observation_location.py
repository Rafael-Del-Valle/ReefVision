"""Policy for selecting the native-image point that represents an organism observation."""

from __future__ import annotations

from math import isfinite

from reefvision.domain.errors import ValidationError
from reefvision.schemas.video_observation_location import VideoObservationImageLocation


def select_video_observation_image_location(
    *,
    bbox: tuple[float, float, float, float],
    image_width_px: int,
    image_height_px: int,
    explicit_point: tuple[float, float] | None = None,
) -> VideoObservationImageLocation:
    """Select an explicit organism point when available, otherwise the bbox center."""

    if image_width_px <= 0 or image_height_px <= 0:
        raise ValidationError("Observation image dimensions must be positive")

    x, y, width, height = bbox
    if not all(isfinite(value) for value in bbox):
        raise ValidationError("Observation bounding box values must be finite")
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ValidationError(
            "Observation bounding box requires a nonnegative origin and positive dimensions"
        )
    if x + width > image_width_px or y + height > image_height_px:
        raise ValidationError("Observation bounding box exceeds native image bounds")

    if explicit_point is None:
        pixel_x = x + width / 2.0
        pixel_y = y + height / 2.0
        method = "bbox_center"
    else:
        pixel_x, pixel_y = explicit_point
        if not isfinite(pixel_x) or not isfinite(pixel_y):
            raise ValidationError("Explicit observation point must be finite")
        if pixel_x < 0 or pixel_x >= image_width_px or pixel_y < 0 or pixel_y >= image_height_px:
            raise ValidationError("Explicit observation point exceeds native image bounds")
        if not (x <= pixel_x <= x + width and y <= pixel_y <= y + height):
            raise ValidationError("Explicit observation point must lie within the observation bbox")
        method = "explicit_point"

    return VideoObservationImageLocation(
        schema_version="video-observation-image-location-0001",
        bbox=bbox,
        pixel_x=pixel_x,
        pixel_y=pixel_y,
        method=method,
    )
