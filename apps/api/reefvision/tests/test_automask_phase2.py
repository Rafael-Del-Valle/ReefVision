from __future__ import annotations

from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from reefvision.tests.test_annotations import create_project


def _two_tone_png() -> bytes:
    image = Image.new("RGB", (40, 20), (220, 40, 40))
    pixels = image.load()
    for y in range(20):
        for x in range(20, 40):
            pixels[x, y] = (30, 50, 220)
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def test_automask_confines_a_large_brush_to_seed_similar_pixels(
    client: TestClient,
) -> None:
    project = create_project(client, "Auto Mask study")
    imported = client.post(
        f"/api/v1/projects/{project['id']}/imports/images",
        files=[("files", ("two-tone.png", _two_tone_png(), "image/png"))],
        data={"relative_paths": "automask/two-tone.png"},
    )
    assert imported.status_code == 200, imported.text
    image_id = imported.json()["successful"][0]["image_id"]
    class_id = project["label_classes"][0]["id"]

    response = client.post(
        f"/api/v1/images/{image_id}/raster-mask-edits",
        json={
            "base_revision": 0,
            "mask_annotation_id": None,
            "label_class_id": class_id,
            "mode": "paint",
            "brush_radius": 18,
            "strokes": [{"points": [{"x": 14, "y": 10}, {"x": 18, "y": 10}]}],
            "auto_mask_enabled": True,
            "auto_mask_color_tolerance": 35,
            "auto_mask_luminance_tolerance": 25,
            "auto_mask_edge_sensitivity": 0.7,
            "auto_mask_contiguous": True,
            "auto_mask_sample_radius": 1,
        },
    )

    assert response.status_code == 200, response.text
    mask = response.json()["mask_annotation"]
    assert mask["source_type"] == "human_automask"
    assert mask["x_max"] <= 21
    assert 100 < mask["area_pixels"] < 500

    content = client.get(
        f"/api/v1/mask-annotations/{mask['id']}/content",
        params={"revision": mask["revision"]},
    )
    assert content.status_code == 200, content.text
    rendered = Image.open(BytesIO(content.content)).convert("L")
    assert rendered.getpixel((10, 10)) > 0
    assert rendered.getpixel((30, 10)) == 0
