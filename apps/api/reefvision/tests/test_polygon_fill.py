from __future__ import annotations

from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from reefvision.config import Settings
from reefvision.domain.errors import ValidationError
from reefvision.storage import raster_edits
from reefvision.tests.test_annotations import create_project, import_one


def test_polygon_fill_preserves_connected_pixel_region_and_simplifies() -> None:
    source = Image.new("RGB", (8, 6), "white")
    draw = ImageDraw.Draw(source)
    draw.rectangle((1, 1, 3, 3), fill="black")
    draw.rectangle((6, 1, 7, 2), fill="black")
    points = raster_edits.polygon_fill_from_source(source, seed_x=2, seed_y=2, tolerance=0)
    assert points == [(1, 1), (4, 1), (4, 4), (1, 4)]
    assert points == raster_edits.polygon_fill_from_source(source, seed_x=2, seed_y=2, tolerance=0)


def test_polygon_fill_tolerance_and_single_pixel_at_image_edge() -> None:
    source = Image.new("RGB", (3, 1), (100, 100, 100))
    source.putpixel((1, 0), (108, 95, 102))
    source.putpixel((2, 0), (140, 100, 100))
    assert raster_edits.polygon_fill_from_source(source, seed_x=0, seed_y=0, tolerance=10) == [
        (0, 0),
        (2, 0),
        (2, 1),
        (0, 1),
    ]
    assert raster_edits.polygon_fill_from_source(source, seed_x=2, seed_y=0, tolerance=0) == [
        (2, 0),
        (3, 0),
        (3, 1),
        (2, 1),
    ]


def test_polygon_fill_rejects_holes_and_empty_masks() -> None:
    source = Image.new("RGB", (5, 5), "black")
    source.putpixel((2, 2), (255, 255, 255))
    with pytest.raises(ValidationError, match="holes"):
        raster_edits.polygon_fill_from_source(source, seed_x=0, seed_y=0, tolerance=0)
    with pytest.raises(ValidationError, match="empty"):
        raster_edits.polygon_from_binary_region(Image.new("L", (4, 4)))


@pytest.mark.parametrize("x,y,tolerance", [(-1, 0, 0), (3, 0, 0), (0, 1, 0), (0, 0, -1)])
def test_polygon_fill_rejects_invalid_seed_or_tolerance(x: int, y: int, tolerance: int) -> None:
    with pytest.raises(ValidationError):
        raster_edits.polygon_fill_from_source(
            Image.new("RGB", (3, 1)), seed_x=x, seed_y=y, tolerance=tolerance
        )


def test_polygon_fill_preview_saves_as_normal_polygon(client: TestClient) -> None:
    project = create_project(client, "Polygon Fill")
    image_id = import_one(client, project["id"])["successful"][0]["image_id"]
    response = client.post(
        f"/api/v1/images/{image_id}/polygon-fill",
        json={"seed": {"x": 0.4, "y": 0.7}, "tolerance": 0},
    )
    assert response.status_code == 200, response.text
    points = response.json()["points"]
    before = client.get(f"/api/v1/images/{image_id}/annotations").json()
    assert before["mask_annotations"] == []
    assert before["image"]["annotation_revision"] == 0
    saved = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "in_progress",
            "annotations": [],
            "mask_annotations": [
                {
                    "id": str(uuid4()),
                    "label_class_id": project["label_classes"][0]["id"],
                    "geometry_kind": "polygon",
                    "points": points,
                }
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    mask = saved.json()["mask_annotations"][0]
    assert mask["geometry_kind"] == "polygon"
    assert mask["area_pixels"] == 80 * 60
    assert mask["mask_path"] is None
    reopened = client.get(f"/api/v1/images/{image_id}/annotations").json()["mask_annotations"][0]
    for key in ("id", "polygon_json", "area_pixels", "geometry_kind", "label_class_id"):
        assert reopened[key] == mask[key]


def test_polygon_fill_uses_16_bit_tiff_intensity_boundaries(client: TestClient) -> None:
    source = Image.new("I;16", (7, 7), 50000)
    for y in range(2, 5):
        for x in range(2, 5):
            source.putpixel((x, y), 5000)
    stream = BytesIO()
    source.save(stream, format="TIFF")

    project = create_project(client, "16-bit Fill Object")
    imported = client.post(
        f"/api/v1/projects/{project['id']}/imports/images",
        files=[("files", ("holes-16bit.tif", stream.getvalue(), "image/tiff"))],
        data={"relative_paths": "holes-16bit.tif"},
    ).json()
    image_id = imported["successful"][0]["image_id"]

    response = client.post(
        f"/api/v1/images/{image_id}/polygon-fill",
        json={"seed": {"x": 3, "y": 3}, "tolerance": 0},
    )

    assert response.status_code == 200, response.text
    assert response.json()["points"] == [
        {"x": 2.0, "y": 2.0},
        {"x": 5.0, "y": 2.0},
        {"x": 5.0, "y": 5.0},
        {"x": 2.0, "y": 5.0},
    ]


def test_polygon_fill_api_validates_inputs(client: TestClient) -> None:
    project = create_project(client, "Fill invalid input")
    image_id = import_one(client, project["id"])["successful"][0]["image_id"]
    endpoint = f"/api/v1/images/{image_id}/polygon-fill"
    assert client.post(endpoint, json={"seed": {"x": 80, "y": 0}}).status_code == 400
    assert (
        client.post(endpoint, json={"seed": {"x": 0, "y": 0}, "tolerance": 256}).status_code == 422
    )
    assert (
        client.post(
            f"/api/v1/images/{uuid4()}/polygon-fill", json={"seed": {"x": 0, "y": 0}}
        ).status_code
        == 404
    )


def test_polygon_fill_rejects_touching_boundaries() -> None:
    mask = Image.new("L", (4, 4))
    for point in [(0, 0), (1, 0), (2, 0), (0, 1), (2, 1), (1, 2), (2, 2)]:
        mask.putpixel(point, 255)
    with pytest.raises(ValidationError, match="touching"):
        raster_edits.polygon_from_binary_region(mask)


def test_polygon_fill_api_preserves_source_and_rejects_holes(
    client: TestClient, test_settings: Settings
) -> None:
    source = Image.new("RGB", (7, 7), "black")
    source.putpixel((3, 3), (255, 255, 255))
    stream = BytesIO()
    source.save(stream, format="PNG")
    project = create_project(client, "Fill holes")
    imported = client.post(
        f"/api/v1/projects/{project['id']}/imports/images",
        files=[("files", ("holes.png", stream.getvalue(), "image/png"))],
        data={"relative_paths": "holes.png"},
    ).json()
    image_id = imported["successful"][0]["image_id"]
    before = client.get(f"/api/v1/images/{image_id}/annotations").json()
    path = test_settings.resolved_data_dir / before["image"]["managed_path"]
    original = path.read_bytes()
    response = client.post(
        f"/api/v1/images/{image_id}/polygon-fill", json={"seed": {"x": 0, "y": 0}}
    )
    assert response.status_code == 400
    assert "holes" in response.json()["detail"]
    assert path.read_bytes() == original
    assert client.get(f"/api/v1/images/{image_id}/annotations").json() == before
    path.write_bytes(b"broken image fixture")
    failed = client.post(f"/api/v1/images/{image_id}/polygon-fill", json={"seed": {"x": 0, "y": 0}})
    assert failed.status_code == 400
    assert "could not be read" in failed.json()["detail"]
