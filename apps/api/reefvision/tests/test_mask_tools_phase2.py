from __future__ import annotations

import numpy as np
import pytest

from reefvision.ml.mask_tools import (
    boolean_masks,
    closing,
    convex_hull,
    densify_ring,
    dilate,
    erode,
    fill_holes,
    flood_select,
    mask_iou,
    mask_to_rings,
    opening,
    polygon_quality,
    polygon_to_mask,
    raster_quality,
    remove_small_components,
    self_intersections,
    simplify_ring,
    snap_ring,
)


def test_polygon_editing_normalization_simplification_and_qa() -> None:
    rectangle = [(10.0, 10.0), (20.0, 10.0), (20.0, 20.0), (10.0, 20.0)]
    dense = densify_ring(rectangle, maximum_segment_length=2)
    assert len(dense) > len(rectangle)
    simplified = simplify_ring(dense, tolerance=0.1)
    assert len(simplified) == 4
    quality = polygon_quality(rectangle, width=30, height=30)
    assert quality.area == pytest.approx(100)
    assert quality.perimeter == pytest.approx(40)
    assert quality.self_intersections == ()

    bow_tie = [(5.0, 5.0), (25.0, 25.0), (5.0, 25.0), (25.0, 5.0)]
    assert self_intersections(bow_tie)
    repaired = convex_hull(bow_tie)
    assert not self_intersections(repaired)
    snapped = snap_ring(
        [(0.8, 2), (29.1, 2), (29.2, 28.8), (0.4, 29.4)],
        width=30,
        height=30,
        edge_distance=1,
    )
    assert {point[0] for point in snapped} == {0.0, 30.0}


def test_raster_boolean_morphology_conversion_and_quality() -> None:
    first = polygon_to_mask(
        [(5, 5), (20, 5), (20, 20), (5, 20)],
        width=32,
        height=32,
    )
    second = polygon_to_mask(
        [(15, 10), (28, 10), (28, 25), (15, 25)],
        width=32,
        height=32,
    )
    union = boolean_masks(first, second, operation="union")
    intersection = boolean_masks(first, second, operation="intersection")
    subtraction = boolean_masks(first, second, operation="subtract")
    assert union.sum() > first.sum()
    assert 0 < intersection.sum() < first.sum()
    assert subtraction.sum() + intersection.sum() == first.sum()
    assert mask_iou(first, first) == 1

    expanded = dilate(first, radius=2)
    contracted = erode(first, radius=2)
    assert expanded.sum() > first.sum() > contracted.sum()
    assert opening(expanded, radius=1).sum() <= expanded.sum()
    assert closing(contracted, radius=1).sum() >= contracted.sum()

    with_hole = first.copy()
    with_hole[10:13, 10:13] = False
    filled = fill_holes(with_hole, maximum_area=20)
    assert filled.sum() == first.sum()
    noisy = first.copy()
    noisy[0, 0] = True
    cleaned = remove_small_components(noisy, minimum_area=4)
    assert not cleaned[0, 0]
    quality = raster_quality(with_hole)
    assert quality.component_count == 1
    assert quality.hole_count == 1
    assert quality.bounds == (5, 5, 21, 21)
    rings = mask_to_rings(with_hole)
    assert len(rings) == 2


def test_magic_wand_flood_selection_is_contiguous() -> None:
    image = np.zeros((20, 20, 3), dtype=np.uint8)
    image[2:8, 2:8] = (100, 110, 120)
    image[12:18, 12:18] = (100, 110, 120)
    selected = flood_select(image, seed_x=4, seed_y=4, tolerance=1, connectivity=8)
    assert selected[4, 4]
    assert not selected[14, 14]
    assert int(selected.sum()) == 36
