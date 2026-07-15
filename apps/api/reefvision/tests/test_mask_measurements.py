from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from reefvision.services.mask_measurements import (
    _raster_measurements,
    _raster_pixel_active,
)
from reefvision.tests.test_annotations import create_project, import_one


def test_polygon_measurements_include_contained_polyp_density(
    client: TestClient,
) -> None:
    project = create_project(client, "Mask measurements")
    report = import_one(client, project["id"], size=(100, 80))
    image_id = report["successful"][0]["image_id"]
    label_class_id = project["label_classes"][0]["id"]
    mask_id = "8445d0dc-a1e6-4c5a-9989-93b47a686979"

    saved = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "annotated",
            "annotations": [
                {
                    "id": "2e33c71f-ab7a-4888-bd69-a3ddd08b7be5",
                    "label_class_id": label_class_id,
                    "x_min": 12,
                    "y_min": 12,
                    "x_max": 18,
                    "y_max": 18,
                },
                {
                    "id": "277e8873-2a43-4cca-8076-22bbf1050841",
                    "label_class_id": label_class_id,
                    "x_min": 45,
                    "y_min": 45,
                    "x_max": 55,
                    "y_max": 55,
                },
            ],
            "mask_annotations": [
                {
                    "id": mask_id,
                    "label_class_id": label_class_id,
                    "geometry_kind": "polygon",
                    "points": [
                        {"x": 10, "y": 10},
                        {"x": 30, "y": 10},
                        {"x": 30, "y": 20},
                        {"x": 10, "y": 20},
                    ],
                }
            ],
        },
    )
    assert saved.status_code == 200, saved.text

    response = client.get(f"/api/v1/mask-annotations/{mask_id}/measurements")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["geometry_kind"] == "polygon"
    assert payload["area_pixels"] == 200
    assert payload["perimeter_pixels"] == pytest.approx(60.0)
    assert payload["centroid_x"] == pytest.approx(20.0)
    assert payload["centroid_y"] == pytest.approx(15.0)
    assert payload["contained_box_count"] == 1
    assert payload["contained_box_density_per_1000_pixels"] == pytest.approx(5.0)


def test_raster_measurements_use_pixel_edges_and_centers(tmp_path: Path) -> None:
    path = tmp_path / "mask.png"
    image = Image.new("L", (10, 10), 0)
    for x in range(2, 6):
        for y in range(3, 6):
            image.putpixel((x, y), 255)
    image.save(path)

    area, perimeter, centroid_x, centroid_y, raster = _raster_measurements(path)

    assert area == 12
    assert perimeter == 14.0
    assert centroid_x == pytest.approx(4.0)
    assert centroid_y == pytest.approx(4.5)
    assert _raster_pixel_active(raster, 2, 3)
    assert _raster_pixel_active(raster, 5, 5)
    assert not _raster_pixel_active(raster, 1, 3)


def test_deleted_mask_measurements_return_not_found(client: TestClient) -> None:
    project = create_project(client, "Deleted mask measurements")
    report = import_one(client, project["id"])
    image_id = report["successful"][0]["image_id"]
    label_class_id = project["label_classes"][0]["id"]
    mask_id = "f1a1fed1-e2fb-4ea1-bfad-49201fd15ae3"

    created = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "in_progress",
            "annotations": [],
            "mask_annotations": [
                {
                    "id": mask_id,
                    "label_class_id": label_class_id,
                    "geometry_kind": "polygon",
                    "points": [
                        {"x": 5, "y": 5},
                        {"x": 20, "y": 5},
                        {"x": 20, "y": 20},
                    ],
                }
            ],
        },
    )
    assert created.status_code == 200

    deleted = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 1,
            "annotation_status": "in_progress",
            "annotations": [],
            "deleted_mask_annotation_ids": [mask_id],
        },
    )
    assert deleted.status_code == 200

    response = client.get(f"/api/v1/mask-annotations/{mask_id}/measurements")
    assert response.status_code == 404
