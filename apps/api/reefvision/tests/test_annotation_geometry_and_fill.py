import pytest
from PIL import Image, ImageDraw
from pydantic import ValidationError as PydanticValidationError

from reefvision.schemas.annotations import MaskAnnotationDraft
from reefvision.storage.raster_edits import _flood_fill_from_source


def test_rotated_box_requires_exactly_four_points() -> None:
    with pytest.raises(PydanticValidationError):
        MaskAnnotationDraft(
            id="box-1",
            label_class_id="class-1",
            geometry_kind="rotated_box",
            points=[{"x": 0, "y": 0}, {"x": 10, "y": 0}, {"x": 10, "y": 10}],
        )

    draft = MaskAnnotationDraft(
        id="box-1",
        label_class_id="class-1",
        geometry_kind="rotated_box",
        points=[
            {"x": 0, "y": 0},
            {"x": 10, "y": 0},
            {"x": 10, "y": 10},
            {"x": 0, "y": 10},
        ],
    )
    assert draft.geometry_kind == "rotated_box"
    assert len(draft.points) == 4


def test_flood_fill_uses_only_contiguous_source_region() -> None:
    source = Image.new("RGB", (8, 5), "white")
    draw = ImageDraw.Draw(source)
    draw.rectangle((1, 1, 3, 3), fill=(20, 30, 40))
    draw.rectangle((6, 1, 7, 2), fill=(20, 30, 40))
    mask = Image.new("L", source.size, 0)

    filled = _flood_fill_from_source(mask, source, seed_x=2, seed_y=2, tolerance=0)

    assert filled == 9
    assert mask.getpixel((2, 2)) == 255
    assert mask.getpixel((6, 1)) == 0


def test_flood_fill_tolerance_accepts_small_variation() -> None:
    source = Image.new("RGB", (3, 1), (100, 100, 100))
    source.putpixel((1, 0), (108, 95, 102))
    source.putpixel((2, 0), (140, 100, 100))
    mask = Image.new("L", source.size, 0)

    filled = _flood_fill_from_source(mask, source, seed_x=0, seed_y=0, tolerance=10)

    assert filled == 2
    assert list(mask.tobytes()) == [255, 255, 0]


def test_flood_fill_keeps_diagonally_connected_space_reachable_around_obstacles() -> None:
    source = Image.new("RGB", (6, 6), (220, 220, 220))
    target = (20, 30, 40)
    for x, y in [
        (1, 1),
        (2, 1),
        (1, 2),
        (2, 2),
        (3, 3),
        (4, 3),
        (3, 4),
        (4, 4),
    ]:
        source.putpixel((x, y), target)
    mask = Image.new("L", source.size, 0)

    filled = _flood_fill_from_source(mask, source, seed_x=1, seed_y=1, tolerance=0)

    assert filled == 8
    assert mask.getpixel((4, 4)) == 255
