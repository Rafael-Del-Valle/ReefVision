"""Source-pixel mask conversion preserves holes and disconnected components."""

from io import BytesIO

import pytest
from PIL import Image

from reefvision.storage.segmentation_metric_masks import (
    binary_mask_to_runs,
    make_scored_mask,
    png_to_runs,
    polygon_to_runs,
)


def mask_png() -> bytes:
    image = Image.new("L", (6, 5), 0)
    for x, y in (
        (1, 0),
        (3, 0),
        (1, 1),
        (3, 1),
        (1, 2),
        (2, 2),
        (3, 2),
    ):
        image.putpixel((x, y), 255)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_raster_runs_preserve_holes_and_disconnected_regions() -> None:
    assert png_to_runs(mask_png(), width=6, height=5) == (
        (0, 1, 2),
        (0, 3, 4),
        (1, 1, 2),
        (1, 3, 4),
        (2, 1, 4),
    )


def test_polygon_uses_source_pixels_not_bounding_box() -> None:
    runs = polygon_to_runs([[1, 1], [3, 1], [3, 3], [1, 3]], width=5, height=5)
    assert runs == ((1, 1, 4), (2, 1, 4), (3, 1, 4))
    assert make_scored_mask(
        runs, image_id="a", class_id="polyp", score=0.9, width=5, height=5
    ).runs == runs


def test_binary_mask_uses_nonzero_pixel_convention() -> None:
    image = Image.new("L", (2, 1), 0)
    image.putpixel((1, 0), 1)
    assert binary_mask_to_runs(image, width=2, height=1) == ((0, 1, 2),)


@pytest.mark.parametrize("payload", [b"", b"not a png", b"\x89PNG\r\n\x1a\ncorrupt"])
def test_corrupt_and_non_png_bytes_fail_closed(payload: bytes) -> None:
    with pytest.raises(ValueError):
        png_to_runs(payload, width=6, height=5)


def test_wrong_dimensions_fail_closed() -> None:
    with pytest.raises(ValueError, match="dimensions"):
        png_to_runs(mask_png(), width=7, height=5)


def test_empty_mask_fails_closed() -> None:
    image = Image.new("L", (4, 3), 0)
    with pytest.raises(ValueError, match="no occupied"):
        binary_mask_to_runs(image, width=4, height=3)


def test_self_intersection_and_out_of_bounds_rejected() -> None:
    invalid = (
        [[0, 0], [2, 0], [9, 2]],
        [[0, 0], [2, float("nan")], [2, 2]],
        [[0, 0], [2, 0]],
        [[1, 1], [4, 4], [1, 4], [4, 1]],
    )
    for points in invalid:
        with pytest.raises(ValueError):
            polygon_to_runs(points, width=5, height=5)


def test_zero_or_oversized_source_dimensions_rejected() -> None:
    with pytest.raises(ValueError, match="dimensions"):
        png_to_runs(mask_png(), width=0, height=5)
    with pytest.raises(ValueError, match="dimensions"):
        polygon_to_runs([[1, 1], [4, 1], [4, 4]], width=100_001, height=100_001)
