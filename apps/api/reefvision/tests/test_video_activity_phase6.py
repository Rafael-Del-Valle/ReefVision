from __future__ import annotations

import io
from typing import cast

import pytest
from fastapi.testclient import TestClient

from reefvision.services import video_assets as video_assets_module
from reefvision.tests.test_annotations import create_project


def _fake_metadata(_path: object) -> dict[str, float | int]:
    return {
        "width_px": 200,
        "height_px": 100,
        "frame_count": 6,
        "fps": 10.0,
        "duration_seconds": 0.6,
    }


def _setup_track(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, object], dict[str, object]]:
    project = create_project(client, "Fish activity analytics")
    monkeypatch.setattr(video_assets_module, "_inspect_video", _fake_metadata)
    video_response = client.post(
        f"/api/v1/projects/{project['id']}/imports/videos",
        files={"file": ("activity.mp4", io.BytesIO(b"video"), "video/mp4")},
    )
    assert video_response.status_code == 201, video_response.text
    video = video_response.json()
    classes = cast(list[dict[str, object]], project["label_classes"])
    track_response = client.post(
        f"/api/v1/videos/{video['id']}/tracks",
        json={
            "label_class_id": str(classes[0]["id"]),
            "keyframes": [
                {"frame": 0, "bbox": [0, 0, 10, 10]},
                {"frame": 1, "bbox": [0, 0, 10, 10]},
                {"frame": 2, "bbox": [10, 0, 10, 10]},
                {"frame": 3, "bbox": [20, 0, 10, 10]},
                {"frame": 4, "bbox": [20, 0, 10, 10]},
                {"frame": 5, "bbox": [30, 0, 10, 10]},
            ],
            "interpolation": "linear",
            "status": "verified",
        },
    )
    assert track_response.status_code == 201, track_response.text
    return video, track_response.json()


def test_activity_requires_calibration(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _video, track = _setup_track(client, monkeypatch)
    response = client.post(
        f"/api/v1/video-tracks/{track['id']}/activity-analytics",
        json={"speed_threshold_per_second": 5.0},
    )
    assert response.status_code == 404


def test_activity_reports_calibrated_active_fraction_and_bouts(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video, track = _setup_track(client, monkeypatch)
    calibration = client.put(
        f"/api/v1/videos/{video['id']}/calibration",
        json={
            "unit": "cm",
            "reference_distance": 10,
            "reference_pixels": 100,
            "method": "known_length",
        },
    )
    assert calibration.status_code == 200, calibration.text

    response = client.post(
        f"/api/v1/video-tracks/{track['id']}/activity-analytics",
        json={
            "speed_threshold_per_second": 5.0,
            "start_frame": 0,
            "end_frame": 5,
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["schema_version"] == "video-track-activity-0001"
    assert result["trajectory_policy"] == "configured_track_interpolation"
    assert result["distance_unit"] == "cm"
    assert result["speed_threshold_per_second"] == pytest.approx(5.0)
    assert result["speed_threshold_pixels_per_second"] == pytest.approx(50.0)
    assert result["evaluated_seconds"] == pytest.approx(0.5)
    assert result["active_seconds"] == pytest.approx(0.3)
    assert result["rest_seconds"] == pytest.approx(0.2)
    assert result["active_fraction"] == pytest.approx(0.6)
    assert result["active_bout_count"] == 2
    assert result["rest_bout_count"] == 2
    assert result["mean_active_bout_seconds"] == pytest.approx(0.15)
    assert result["maximum_active_bout_seconds"] == pytest.approx(0.2)
    assert result["mean_rest_bout_seconds"] == pytest.approx(0.1)
    assert result["mean_active_speed_per_second"] == pytest.approx(10.0)
    assert result["maximum_speed_per_second"] == pytest.approx(10.0)
    assert [item["active"] for item in result["intervals"]] == [
        False,
        True,
        True,
        False,
        True,
    ]
    assert [item["state"] for item in result["bouts"]] == [
        "rest",
        "active",
        "rest",
        "active",
    ]


def test_minimum_active_bout_duration_reclassifies_short_bursts_as_rest(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video, track = _setup_track(client, monkeypatch)
    set_scale = client.put(
        f"/api/v1/videos/{video['id']}/calibration",
        json={
            "unit": "cm",
            "reference_distance": 10,
            "reference_pixels": 100,
        },
    )
    assert set_scale.status_code == 200

    response = client.post(
        f"/api/v1/video-tracks/{track['id']}/activity-analytics",
        json={
            "speed_threshold_per_second": 5.0,
            "minimum_active_bout_seconds": 0.15,
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["active_seconds"] == pytest.approx(0.2)
    assert result["rest_seconds"] == pytest.approx(0.3)
    assert result["active_fraction"] == pytest.approx(0.4)
    assert result["active_bout_count"] == 1
    assert result["rest_bout_count"] == 2
    assert result["mean_active_bout_seconds"] == pytest.approx(0.2)
    assert result["maximum_active_bout_seconds"] == pytest.approx(0.2)
    assert result["mean_rest_bout_seconds"] == pytest.approx(0.15)
    assert [item["state"] for item in result["bouts"]] == [
        "rest",
        "active",
        "rest",
    ]
