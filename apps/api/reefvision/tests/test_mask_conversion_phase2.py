from __future__ import annotations

import base64
import io

from fastapi.testclient import TestClient
from PIL import Image


def _polygon(outer, holes=None):
    return {
        "outer": [{"x": x, "y": y} for x, y in outer],
        "holes": [[{"x": x, "y": y} for x, y in ring] for ring in (holes or [])],
    }


def test_polygon_raster_round_trip_preserves_components_and_holes(
    client: TestClient,
) -> None:
    polygons = [
        _polygon(
            [(1, 1), (10, 1), (10, 10), (1, 10)],
            holes=[[(3, 3), (8, 3), (8, 8), (3, 8)]],
        ),
        _polygon([(13, 2), (18, 2), (18, 7), (13, 7)]),
    ]
    rasterized = client.post(
        "/api/v1/geometry/masks/polygons-to-raster",
        json={
            "polygons": polygons,
            "image_width": 20,
            "image_height": 12,
            "rle_order": "coco_fortran",
        },
    )
    assert rasterized.status_code == 200, rasterized.text
    raster = rasterized.json()
    assert raster["quality"]["component_count"] == 2
    assert raster["quality"]["hole_count"] == 1
    assert raster["raster"]["order"] == "coco_fortran"
    preview = Image.open(io.BytesIO(base64.b64decode(raster["preview_png_base64"])))
    assert preview.size == (20, 12)

    vectorized = client.post(
        "/api/v1/geometry/masks/raster-to-polygons",
        json={
            "raster": raster["raster"],
            "simplify_tolerance": 0,
            "minimum_component_area": 1,
            "preserve_holes": True,
        },
    )
    assert vectorized.status_code == 200, vectorized.text
    payload = vectorized.json()
    assert payload["quality"]["component_count"] == 2
    assert payload["quality"]["hole_count"] == 1
    assert len(payload["polygons"]) == 2
    assert sum(len(item["holes"]) for item in payload["polygons"]) == 1
    assert payload["round_trip_iou"] == 1.0
    assert payload["cleaned_raster"]["order"] == "coco_fortran"


def test_rasterized_repair_removes_polygon_self_intersections(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/geometry/polygons/repair-rasterized",
        json={
            "polygons": [
                _polygon([(1, 1), (10, 10), (1, 10), (10, 1)]),
            ],
            "image_width": 12,
            "image_height": 12,
            "simplify_tolerance": 0,
            "preserve_holes": True,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["original_self_intersection_count"] >= 1
    assert payload["repaired_self_intersection_count"] == 0
    assert payload["polygons"]
    assert payload["round_trip_iou"] == 1.0
    assert payload["quality"]["foreground_pixels"] > 0
    assert any("Self-intersections were repaired" in item for item in payload["warnings"])
