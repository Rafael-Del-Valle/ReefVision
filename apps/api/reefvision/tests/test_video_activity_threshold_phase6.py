from __future__ import annotations

import io
from typing import cast

import pytest
from fastapi.testclient import TestClient

from reefvision.services import video_assets as video_assets_module
from reefvision.tests.test_annotations import create_project


def _fake_metadata(_path: object) -> dict[str, float | int]:
    return {
        "width_px": 100,
        "height_px": 60,
        "frame_count": 3,
        "fps": 10.0,
        "duration_seconds": 0.3,
    }


def test_zero_threshold_means_any_positive_movement_not_stationarity(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Zero threshold activity")
    monkeypatch.setattr(video_assets_module, "_inspect_video", _fake_metadata)
    imported = client.post(
        f"/api/v1/projects/{project['id']}/imports/videos",
        files={"file": ("activity.mp4", io.BytesIO(b"video"), "video/mp4")},
    )
    assert imported.status_code == 201, imported.text
    video_id = str(imported.json()["id"])
    classes = cast(list[dict[str, object]], project["label_classes"])
    track = client.post(
        f"/api/v1/videos/{video_id}/tracks",
        json={
            "label_class_id": str(classes[0]["id"]),
            "keyframes": [
                {"frame": 0, "bbox": [0, 0, 10, 10]},
                {"frame": 1, "bbox": [0, 0, 10, 10]},
                {"frame": 2, "bbox": [10, 0, 10, 10]},
            ],
            "interpolation": "linear",
            "status": "verified",
        },
    )
    assert track.status_code == 201, track.text
    calibration = client.put(
        f"/api/v1/videos/{video_id}/calibration",
        json={
            "unit": "cm",
            "reference_distance": 10,
            "reference_pixels": 100,
        },
    )
    assert calibration.status_code == 200

    response = client.post(
        f"/api/v1/video-tracks/{track.json()['id']}/activity-analytics",
        json={"speed_threshold_per_second": 0.0},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert [item["active"] for item in result["intervals"]] == [False, True]
    assert result["active_seconds"] == pytest.approx(0.1)
    assert result["rest_seconds"] == pytest.approx(0.1)
    assert result["active_fraction"] == pytest.approx(0.5)
