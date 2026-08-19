from __future__ import annotations

from io import BytesIO
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from reefvision.services.image_scale_calibration import _candidate_bands
from reefvision.tests.test_annotations import create_project, import_one


def _ruler_image_bytes() -> bytes:
    image = Image.new("RGB", (260, 140), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((15, 35, 245, 115), fill=(235, 235, 225), outline="black", width=2)
    for index, x in enumerate(range(30, 231, 20)):
        height = 60 if index % 5 == 0 else 38 if index % 2 == 0 else 28
        draw.line((x, 105, x, 105 - height), fill="black", width=2)
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def _import_bytes(
    client: TestClient,
    project_id: str,
    *,
    filename: str,
    content: bytes,
) -> str:
    response = client.post(
        f"/api/v1/projects/{project_id}/imports/images",
        files=[("files", (filename, content, "application/octet-stream"))],
        data={"relative_paths": filename},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["successful"][0]["image_id"])


def _save_polygon_mask(
    client: TestClient,
    project: dict[str, Any],
    image_id: str,
) -> str:
    mask_id = "aa30d3f3-f9d2-47d9-bbbe-1bb9ad75a5a2"
    response = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "reviewed",
            "annotations": [],
            "mask_annotations": [
                {
                    "id": mask_id,
                    "label_class_id": project["label_classes"][0]["id"],
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
    assert response.status_code == 200, response.text
    return mask_id


def test_small_image_candidate_bands_stay_inside_image_bounds() -> None:
    bands = _candidate_bands(12, 10, "auto")

    assert bands
    assert all(0 <= band.x_min < band.x_max <= 12 for band in bands)
    assert all(0 <= band.y_min < band.y_max <= 10 for band in bands)


def test_ruler_detection_estimates_pixels_but_never_infers_units(
    client: TestClient,
) -> None:
    project = create_project(client, "Automatic ruler candidate")
    image_id = _import_bytes(
        client,
        project["id"],
        filename="ruler.png",
        content=_ruler_image_bytes(),
    )

    response = client.post(
        f"/api/v1/images/{image_id}/measurement-calibration/ruler-detect",
        json={
            "orientation": "horizontal",
            "roi": {"x_min": 15, "y_min": 35, "x_max": 245, "y_max": 115},
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["method"] == "automatic_ruler"
    assert payload["orientation"] == "horizontal"
    assert payload["base_interval_pixels"] == pytest.approx(20.0, abs=2.5)
    assert payload["interval_count"] >= 4
    assert payload["unit_inferred"] is False
    assert payload["reference_length_required"] is True
    assert 0 <= payload["confidence"] <= 1


def test_calibration_profile_requires_confirmation_and_matching_resolution(
    client: TestClient,
) -> None:
    project = create_project(client, "Calibration profile reuse")
    source = import_one(client, project["id"], filename="source.png", size=(100, 80))
    target = import_one(client, project["id"], filename="target.png", size=(100, 80))
    mismatch = import_one(
        client,
        project["id"],
        filename="mismatch.png",
        size=(120, 80),
    )
    source_id = source["successful"][0]["image_id"]
    target_id = target["successful"][0]["image_id"]
    mismatch_id = mismatch["successful"][0]["image_id"]

    saved = client.put(
        f"/api/v1/images/{source_id}/measurement-calibration",
        json={
            "distance_per_pixel": 0.05,
            "unit": "cm",
            "source": "automatic_ruler",
            "reference_length": 1.0,
            "reference_pixel_length": 20.0,
            "confidence": 0.94,
            "detector": "ruler-periodicity-v1",
            "profile_name": "Canon coral rig",
            "camera_signature": {
                "camera_model": "Example camera",
                "lens_model": "Example macro lens",
                "capture_distance": 45.0,
            },
            "perspective_homography": [
                [0.05, 0.0, 0.0],
                [0.0, 0.05, 0.0],
                [0.0, 0.0, 1.0],
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["camera_signature"]["width_px"] == 100
    assert saved.json()["camera_signature"]["height_px"] == 80

    profiles = client.get(
        f"/api/v1/projects/{project['id']}/measurement-calibration-profiles"
    )
    assert profiles.status_code == 200, profiles.text
    assert [item["profile_name"] for item in profiles.json()] == ["Canon coral rig"]

    refused = client.post(
        f"/api/v1/images/{target_id}/measurement-calibration/apply-profile",
        json={"source_image_id": source_id, "confirm_same_setup": False},
    )
    assert refused.status_code >= 400

    applied = client.post(
        f"/api/v1/images/{target_id}/measurement-calibration/apply-profile",
        json={"source_image_id": source_id, "confirm_same_setup": True},
    )
    assert applied.status_code == 200, applied.text
    applied_payload = applied.json()
    assert applied_payload["distance_per_pixel"] == pytest.approx(0.05)
    assert applied_payload["unit"] == "cm"
    assert applied_payload["source"] == "camera_profile"
    assert applied_payload["profile_source_image_id"] == source_id
    assert applied_payload["perspective_homography"] is None

    wrong_resolution = client.post(
        f"/api/v1/images/{mismatch_id}/measurement-calibration/apply-profile",
        json={"source_image_id": source_id, "confirm_same_setup": True},
    )
    assert wrong_resolution.status_code >= 400


def test_polygon_measurements_use_perspective_homography_in_physical_plane(
    client: TestClient,
) -> None:
    project = create_project(client, "Perspective measurement")
    report = import_one(client, project["id"], size=(100, 80))
    image_id = report["successful"][0]["image_id"]
    mask_id = _save_polygon_mask(client, project, image_id)

    calibration = client.put(
        f"/api/v1/images/{image_id}/measurement-calibration",
        json={
            "distance_per_pixel": 0.1,
            "unit": "cm",
            "source": "charuco",
            "reference_length": 1.0,
            "reference_pixel_length": 10.0,
            "confidence": 0.99,
            "detector": "test-homography",
            "perspective_homography": [
                [0.1, 0.0, 0.0],
                [0.0, 0.1, 0.0],
                [0.0, 0.0, 1.0],
            ],
        },
    )
    assert calibration.status_code == 200, calibration.text

    profile = client.put(
        f"/api/v1/mask-annotations/{mask_id}/measurement-profile",
        json={
            "base_revision": 1,
            "centerline_points": [
                {"x": 10, "y": 15},
                {"x": 30, "y": 15},
            ],
            "surface_model": "none",
        },
    )
    assert profile.status_code == 200, profile.text

    measured = client.get(f"/api/v1/mask-annotations/{mask_id}/measurements")
    assert measured.status_code == 200, measured.text
    payload = measured.json()
    assert payload["area_pixels"] == 200
    assert payload["area_physical"] == pytest.approx(2.0)
    assert payload["perimeter_physical"] == pytest.approx(6.0)
    assert payload["centroid_x_physical"] == pytest.approx(2.0)
    assert payload["centroid_y_physical"] == pytest.approx(1.5)
    assert payload["total_linear_extension_physical"] == pytest.approx(2.0)
    assert payload["perspective_corrected"] is True
    assert payload["calibration_source"] == "charuco"
    assert payload["calibration_confidence"] == pytest.approx(0.99)
