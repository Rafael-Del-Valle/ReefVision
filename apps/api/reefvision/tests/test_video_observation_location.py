from __future__ import annotations

import pytest

from reefvision.domain.errors import ValidationError
from reefvision.services.video_observation_location import (
    select_video_observation_image_location,
)


def test_bbox_center_is_default_observation_location() -> None:
    location = select_video_observation_image_location(
        bbox=(100.0, 200.0, 40.0, 20.0),
        image_width_px=1920,
        image_height_px=1080,
    )

    assert location.schema_version == "video-observation-image-location-0001"
    assert location.bbox == (100.0, 200.0, 40.0, 20.0)
    assert location.pixel_x == pytest.approx(120.0)
    assert location.pixel_y == pytest.approx(210.0)
    assert location.method == "bbox_center"


def test_explicit_point_takes_precedence_and_preserves_bbox() -> None:
    location = select_video_observation_image_location(
        bbox=(100.0, 200.0, 40.0, 20.0),
        image_width_px=1920,
        image_height_px=1080,
        explicit_point=(112.5, 204.25),
    )

    assert location.bbox == (100.0, 200.0, 40.0, 20.0)
    assert location.pixel_x == pytest.approx(112.5)
    assert location.pixel_y == pytest.approx(204.25)
    assert location.method == "explicit_point"


@pytest.mark.parametrize(
    ("bbox", "explicit_point", "message"),
    [
        ((-1.0, 0.0, 10.0, 10.0), None, "nonnegative origin"),
        ((0.0, 0.0, 0.0, 10.0), None, "positive dimensions"),
        ((1915.0, 0.0, 10.0, 10.0), None, "native image bounds"),
        ((100.0, 200.0, 40.0, 20.0), (150.0, 210.0), "within the observation bbox"),
        ((100.0, 200.0, 40.0, 20.0), (1920.0, 210.0), "native image bounds"),
    ],
)
def test_invalid_observation_locations_fail_explicitly(
    bbox: tuple[float, float, float, float],
    explicit_point: tuple[float, float] | None,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        select_video_observation_image_location(
            bbox=bbox,
            image_width_px=1920,
            image_height_px=1080,
            explicit_point=explicit_point,
        )
