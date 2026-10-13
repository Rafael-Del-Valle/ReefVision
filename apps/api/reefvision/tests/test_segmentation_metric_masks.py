"""Pixel-run encoding retains scientific instance-mask topology."""

from io import BytesIO

import pytest
from PIL import Image

from reefvision.domain.segmentation_evaluation import mask_iou
from reefvision.storage.segmentation_metric_masks import (
    binary_mask_to_runs,
    make_scored_mask,
    png_to_runs,
    polygon_to_runs,
)


def mask_png() -> bytes:
    img = Image.new("L", (6, 5), 0)
    for x, y in ((1, 0), (3, 0), (1, 1), (3, 1), (1, 2), (2, 2), (3, 2)):
        img.putpixel((x, y), 255)
    data = BytesIO()
    img.save(data, format="PNG")
    return data.getvalue()


def test_source_png_retains_holes_and_disconnected_components() -> None:
    assert png_to_runs(mask_png(), width=6, height=5) == (
        (0, 1, 2),
        (0, 3, 4),
        (1, 1, 2),
        (1, 3, 4),
        (2, 1, 4),
    )


def test_polygon_is_rasterized_in_source_pixels_not_as_its_box() -> None:
    result = polygon_to_runs(
        [[1, 1], [3, 1], [3, 3], [1, 3]], width=5, height=5
    )
    assert result == ((1, 1, 4), (2, 1, 4), (3, 1, 4))
    scored = make_scored_mask(
        result, image_id="a", class_id="polyp", score=0.9, width=5, height=5
    )
    assert scored.runs == result


def test_true_binary_iou_differs_from_bbox_iou() -> None:
    actual = png_to_runs(mask_png(), width=6, height=5)
    filled = tuple((row, 1, 4) for row in (0, 1, 2))
    score = mask_iou(
        make_scored_mask(actual, image_id="a", class_id="coral", score=1, width=6, height=5),
        make_scored_mask(filled, image_id="a", class_id="coral", score=0.8, width=6, height=5),
    )
    assert score == pytest.approx(7 / 9)


def test_one_nonzero_pixel_is_an_instance_mask() -> None:
    x = Image.new("L", (2, 1), 0)
    x.putpixel((1, 0), 1)
    assert binary_mask_to_runs(x, width=2, height=1) == ((0, 1, 2),)


@pytest.mark.parametrize("data", [b"", b"not a png", b"\x89PNG\r\n\x1a\ncorrupt"])
def test_unreadable_png_fails_closed(data: bytes) -> None:
    with pytest.raises(ValueError):
        png_to_runs(data, width=6, height=5)


def test_wrong_source_image_dimensions_are_rejected() -> None:
    with pytest.raises(ValueError, match="dimensions"):
        png_to_runs(mask_png(), width=7, height=5)


def test_empty_mask_is_rejected() -> None:
    with pytest.raises(ValueError, match="no occupied"):
        binary_mask_to_runs(Image.new("L", (4, 3), 0), width=4, height=3)


def test_invalid_or_nonfinite_polygon_coordinates_fail_closed() -> None:
    examples = [
        [[0, 0], [2, 0], [9, 2]],
        [[0, 0], [2, float("nan")], [2, 2]],
        [[0, 0], [2, 0]],
    ]
    for points in examples:
        with pytest.raises(ValueError):
            polygon_to_runs(points, width=5, height=5)
