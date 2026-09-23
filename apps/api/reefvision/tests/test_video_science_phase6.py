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

    analytics = client.get(f"/api/v1/video-tracks/{track['id']}/calibrated-analytics")
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


def test_georeferencing_readiness_api_reports_missing_prerequisites(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Georeferencing readiness")
    video = _video(client, str(project["id"]), monkeypatch)

    response = client.get(f"/api/v1/videos/{video['id']}/georeferencing-readiness")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ready"] is False
    assert payload["state"] == "missing_calibration"
    assert {issue["code"] for issue in payload["issues"]} == {
        "missing_calibration",
        "missing_surface_reference",
        "missing_telemetry",
    }


def test_georeferencing_calibration_persists_full_camera_model(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Georeferencing calibration")
    video = _video(client, str(project["id"]), monkeypatch)
    video_id = str(video["id"])
    endpoint = f"/api/v1/videos/{video_id}/georeferencing-calibration"

    assert client.get(endpoint).status_code == 404

    created = client.put(
        endpoint,
        json={
            "width_px": 200,
            "height_px": 100,
            "fx_px": 150.0,
            "fy_px": 151.0,
            "cx_px": 100.5,
            "cy_px": 49.5,
            "distortion_coefficients": [0.1, -0.2, 0.001, -0.001, 0.05],
            "digital_zoom_ratio": 1.0,
            "camera_mode": "DJI Mavic 3T RGB wide",
            "source": "checkerboard calibration fixture",
            "evidence": "Synthetic full camera model used for API persistence testing",
        },
    )
    assert created.status_code == 200, created.text
    calibration = created.json()
    assert calibration["schema_version"] == "video-georeferencing-calibration-0001"
    assert calibration["width_px"] == 200
    assert calibration["height_px"] == 100
    assert calibration["distortion_coefficients"] == [0.1, -0.2, 0.001, -0.001, 0.05]
    assert calibration["camera_mode"] == "DJI Mavic 3T RGB wide"
    assert len(calibration["checksum_sha256"]) == 64
    assert calibration["calibration_revision"] == 1

    fetched = client.get(endpoint)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["checksum_sha256"] == calibration["checksum_sha256"]
    assert fetched.json()["evidence"] == calibration["evidence"]

    replacement = client.put(
        endpoint,
        json={
            "width_px": 200,
            "height_px": 100,
            "fx_px": 150.0,
            "fy_px": 151.0,
            "cx_px": 100.5,
            "cy_px": 49.5,
            "distortion_coefficients": [0.1, -0.2, 0.001, -0.001, 0.05],
            "digital_zoom_ratio": 1.0,
            "camera_mode": "DJI Mavic 3T RGB wide",
            "source": "checkerboard calibration fixture",
            "evidence": "Reviewed calibration evidence",
        },
    )
    assert replacement.status_code == 200, replacement.text
    assert replacement.json()["calibration_revision"] == 2
    assert replacement.json()["checksum_sha256"] == calibration["checksum_sha256"]

    mismatch = client.put(
        endpoint,
        json={
            "width_px": 201,
            "height_px": 100,
            "fx_px": 150.0,
            "fy_px": 151.0,
            "cx_px": 100.5,
            "cy_px": 49.5,
            "distortion_coefficients": [],
            "digital_zoom_ratio": 1.0,
            "camera_mode": "wide",
            "source": "invalid fixture",
            "evidence": "Resolution intentionally mismatched",
        },
    )
    assert mismatch.status_code == 400

    cleared = client.delete(endpoint)
    assert cleared.status_code == 204
    assert client.get(endpoint).status_code == 404


def test_metric_depth_samples_back_project_tracks_into_3d(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Depth-aware fish tracking")
    video = _video(client, str(project["id"]), monkeypatch)
    classes = cast(list[dict[str, object]], project["label_classes"])
    track = _track(client, str(video["id"]), str(classes[0]["id"]), 0)

    missing = client.post(
        f"/api/v1/videos/{video['id']}/depth-track-analytics",
        json={
            "unit": "m",
            "samples": [
                {"track_id": track["id"], "frame": 0, "depth": 2.0},
                {"track_id": track["id"], "frame": 2, "depth": 2.0},
            ],
        },
    )
    assert missing.status_code == 404

    calibration = client.put(
        f"/api/v1/videos/{video['id']}/camera-intrinsics",
        json={
            "fx_px": 100,
            "fy_px": 100,
            "cx_px": 5,
            "cy_px": 5,
            "method": "checkerboard",
            "notes": "Synthetic pinhole calibration",
        },
    )
    assert calibration.status_code == 200, calibration.text
    intrinsics = calibration.json()
    assert intrinsics["schema_version"] == "video-camera-intrinsics-0001"
    assert intrinsics["fx_px"] == pytest.approx(100.0)

    response = client.post(
        f"/api/v1/videos/{video['id']}/depth-track-analytics",
        json={
            "unit": "m",
            "samples": [
                {
                    "track_id": track["id"],
                    "frame": 0,
                    "depth": 2.0,
                    "confidence": 0.99,
                },
                {
                    "track_id": track["id"],
                    "frame": 2,
                    "depth": 2.0,
                    "confidence": 0.98,
                },
            ],
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["schema_version"] == "video-depth-track-analytics-0001"
    assert result["unit"] == "m"
    assert len(result["tracks"]) == 1
    analytics = result["tracks"][0]
    assert analytics["observed_frame_count"] == 2
    assert analytics["path_length_3d"] == pytest.approx(0.4)
    assert analytics["displacement_3d"] == pytest.approx(0.4)
    assert analytics["mean_speed_3d_per_second"] == pytest.approx(2.0)
    assert analytics["maximum_speed_3d_per_second"] == pytest.approx(2.0)
    assert analytics["mean_depth"] == pytest.approx(2.0)
    assert analytics["points"][0]["x"] == pytest.approx(0.0)
    assert analytics["points"][1]["x"] == pytest.approx(0.4)
    assert analytics["points"][1]["z"] == pytest.approx(2.0)

    fetched = client.get(f"/api/v1/videos/{video['id']}/camera-intrinsics")
    assert fetched.status_code == 200
    assert fetched.json()["method"] == "checkerboard"

    cleared = client.delete(f"/api/v1/videos/{video['id']}/camera-intrinsics")
    assert cleared.status_code == 204
    assert client.get(f"/api/v1/videos/{video['id']}/camera-intrinsics").status_code == 404


def test_depth_track_samples_must_match_track_support(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Depth track validation")
    video = _video(client, str(project["id"]), monkeypatch)
    classes = cast(list[dict[str, object]], project["label_classes"])
    track = _track(client, str(video["id"]), str(classes[0]["id"]), 0)

    calibration = client.put(
        f"/api/v1/videos/{video['id']}/camera-intrinsics",
        json={"fx_px": 100, "fy_px": 100, "cx_px": 5, "cy_px": 5},
    )
    assert calibration.status_code == 200

    response = client.post(
        f"/api/v1/videos/{video['id']}/depth-track-analytics",
        json={
            "unit": "cm",
            "samples": [
                {"track_id": track["id"], "frame": 0, "depth": 20},
                {"track_id": track["id"], "frame": 4, "depth": 20},
            ],
        },
    )
    assert response.status_code == 400, response.text
    assert "outside the track trajectory" in response.json()["detail"]
