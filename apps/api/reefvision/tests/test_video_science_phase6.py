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
        "frame_count": 5,
        "fps": 10.0,
        "duration_seconds": 0.5,
    }


def _video(
    client: TestClient,
    project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    monkeypatch.setattr(video_assets_module, "_inspect_video", _fake_metadata)
    response = client.post(
        f"/api/v1/projects/{project_id}/imports/videos",
        files={"file": ("school.mp4", io.BytesIO(b"video"), "video/mp4")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _track(
    client: TestClient,
    video_id: str,
    label_class_id: str,
    y: float,
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/videos/{video_id}/tracks",
        json={
            "label_class_id": label_class_id,
            "keyframes": [
                {"frame": 0, "bbox": [0, y, 10, 10]},
                {"frame": 2, "bbox": [20, y, 10, 10]},
            ],
            "interpolation": "linear",
            "status": "verified",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_calibration_converts_track_metrics_to_physical_units(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Calibrated fish tracking")
    video = _video(client, str(project["id"]), monkeypatch)
    classes = cast(list[dict[str, object]], project["label_classes"])
    track = _track(client, str(video["id"]), str(classes[0]["id"]), 0)

    missing = client.get(f"/api/v1/video-tracks/{track['id']}/calibrated-analytics")
    assert missing.status_code == 404

    calibration = client.put(
        f"/api/v1/videos/{video['id']}/calibration",
        json={
            "unit": "cm",
            "reference_distance": 10,
            "reference_pixels": 100,
            "method": "tank ruler",
            "reference_label": "10 cm ruler",
            "notes": "Synthetic acceptance scale",
        },
    )
    assert calibration.status_code == 200, calibration.text
    scale = calibration.json()
    assert scale["schema_version"] == "video-spatial-calibration-0001"
    assert scale["pixels_per_unit"] == pytest.approx(10.0)
    assert scale["units_per_pixel"] == pytest.approx(0.1)
    assert scale["unit"] == "cm"

    analytics = client.get(
        f"/api/v1/video-tracks/{track['id']}/calibrated-analytics"
    )
    assert analytics.status_code == 200, analytics.text
    result = analytics.json()
    assert result["path_length_pixels"] == pytest.approx(20.0)
    assert result["path_length"] == pytest.approx(2.0)
    assert result["displacement_pixels"] == pytest.approx(20.0)
    assert result["displacement"] == pytest.approx(2.0)
    assert result["mean_speed_pixels_per_second"] == pytest.approx(100.0)
    assert result["mean_speed_per_second"] == pytest.approx(10.0)
    assert result["maximum_speed_per_second"] == pytest.approx(10.0)
    assert result["distance_unit"] == "cm"


def test_parallel_tracks_produce_expected_schooling_metrics(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Schooling analytics")
    video = _video(client, str(project["id"]), monkeypatch)
    classes = cast(list[dict[str, object]], project["label_classes"])
    label_class_id = str(classes[0]["id"])
    first = _track(client, str(video["id"]), label_class_id, 0)
    second = _track(client, str(video["id"]), label_class_id, 10)

    calibration = client.put(
        f"/api/v1/videos/{video['id']}/calibration",
        json={
            "unit": "cm",
            "reference_distance": 10,
            "reference_pixels": 100,
        },
    )
    assert calibration.status_code == 200, calibration.text

    response = client.post(
        f"/api/v1/videos/{video['id']}/schooling-analytics",
        json={
            "track_ids": [first["id"], second["id"]],
            "start_frame": 0,
            "end_frame": 2,
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["schema_version"] == "video-schooling-analytics-0001"
    assert result["trajectory_policy"] == "configured_track_interpolation"
    assert result["frames_evaluated"] == 3
    assert result["mean_group_size"] == pytest.approx(2.0)
    assert result["mean_pairwise_distance_pixels"] == pytest.approx(10.0)
    assert result["mean_nearest_neighbor_distance_pixels"] == pytest.approx(10.0)
    assert result["mean_distance_to_centroid_pixels"] == pytest.approx(5.0)
    assert result["mean_pairwise_distance"] == pytest.approx(1.0)
    assert result["mean_nearest_neighbor_distance"] == pytest.approx(1.0)
    assert result["mean_distance_to_centroid"] == pytest.approx(0.5)
    assert result["mean_speed_pixels_per_second"] == pytest.approx(100.0)
    assert result["mean_speed_per_second"] == pytest.approx(10.0)
    assert result["mean_polarization"] == pytest.approx(1.0)
    assert result["distance_unit"] == "cm"
    assert result["frames"][0]["polarization"] is None
    assert result["frames"][1]["polarization"] == pytest.approx(1.0)
    assert result["frames"][2]["polarization"] == pytest.approx(1.0)


def test_calibration_can_be_cleared_and_schooling_requires_scale(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Calibration lifecycle")
    video = _video(client, str(project["id"]), monkeypatch)
    classes = cast(list[dict[str, object]], project["label_classes"])
    first = _track(client, str(video["id"]), str(classes[0]["id"]), 0)
    second = _track(client, str(video["id"]), str(classes[0]["id"]), 10)

    missing = client.post(
        f"/api/v1/videos/{video['id']}/schooling-analytics",
        json={"track_ids": [first["id"], second["id"]]},
    )
    assert missing.status_code == 404

    set_scale = client.put(
        f"/api/v1/videos/{video['id']}/calibration",
        json={
            "unit": "mm",
            "reference_distance": 50,
            "reference_pixels": 100,
        },
    )
    assert set_scale.status_code == 200
    get_scale = client.get(f"/api/v1/videos/{video['id']}/calibration")
    assert get_scale.status_code == 200
    assert get_scale.json()["pixels_per_unit"] == pytest.approx(2.0)

    cleared = client.delete(f"/api/v1/videos/{video['id']}/calibration")
    assert cleared.status_code == 204
    assert client.get(f"/api/v1/videos/{video['id']}/calibration").status_code == 404
