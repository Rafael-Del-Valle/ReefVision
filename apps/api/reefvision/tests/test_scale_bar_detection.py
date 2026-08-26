from __future__ import annotations

from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from reefvision.tests.test_annotations import create_project


def _scale_bar_image_bytes() -> bytes:
    image = Image.new("RGB", (300, 160), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((55, 125, 205, 130), fill="black")
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def test_scale_bar_detection_returns_reviewable_pixel_geometry(
    client: TestClient,
) -> None:
    project = create_project(client, "Automatic scale bar candidate")
    response = client.post(
        f"/api/v1/projects/{project['id']}/imports/images",
        files=[("files", ("scale-bar.png", _scale_bar_image_bytes(), "image/png"))],
        data={"relative_paths": "scale-bar.png"},
    )
    assert response.status_code == 200, response.text
    image_id = response.json()["successful"][0]["image_id"]

    detected = client.post(
        f"/api/v1/images/{image_id}/measurement-calibration/scale-bar-detect",
        json={
            "orientation": "horizontal",
            "roi": {"x_min": 25, "y_min": 105, "x_max": 250, "y_max": 145},
        },
    )

    assert detected.status_code == 200, detected.text
    payload = detected.json()
    assert payload["method"] == "automatic_scale_bar"
    assert payload["orientation"] == "horizontal"
    assert payload["bar_length_pixels"] == pytest.approx(151.0, abs=3.0)
    assert payload["bar_thickness_pixels"] == pytest.approx(6.0, abs=2.0)
    assert payload["polarity"] == "dark"
    assert payload["continuity_score"] >= 0.9
    assert payload["unit_inferred"] is False
    assert payload["reference_length_required"] is True
    assert payload["label_text"] is None
    assert 0.0 <= payload["confidence"] <= 1.0


def test_scale_bar_detection_rejects_flat_image(client: TestClient) -> None:
    project = create_project(client, "No scale bar")
    image = Image.new("RGB", (200, 120), "white")
    stream = BytesIO()
    image.save(stream, format="PNG")
    response = client.post(
        f"/api/v1/projects/{project['id']}/imports/images",
        files=[("files", ("blank.png", stream.getvalue(), "image/png"))],
        data={"relative_paths": "blank.png"},
    )
    assert response.status_code == 200, response.text
    image_id = response.json()["successful"][0]["image_id"]

    detected = client.post(
        f"/api/v1/images/{image_id}/measurement-calibration/scale-bar-detect",
        json={"orientation": "auto"},
    )
    assert detected.status_code >= 400
