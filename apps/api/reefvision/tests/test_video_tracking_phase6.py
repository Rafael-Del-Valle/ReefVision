from __future__ import annotations

import json
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import ModelRegistration, VideoAsset
from reefvision.tests.test_annotations import create_project


def _seed_video(client: TestClient) -> tuple[dict[str, object], str, str]:
    project = create_project(client, "Phase 6 fish tracking")
    label_classes = cast(list[dict[str, object]], project["label_classes"])
    label_class_id = str(label_classes[0]["id"])
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        video = VideoAsset(
            project_id=str(project["id"]),
            original_filename="fish.mp4",
            managed_path=f"projects/{project['id']}/videos/fish.mp4",
            sha256="b" * 64,
            media_type="video/mp4",
            width_px=100,
            height_px=100,
            frame_count=21,
            fps=10,
            duration_seconds=2,
            metadata_json={"source_modified": False},
        )
        session.add(video)
        session.commit()
        session.refresh(video)
        return project, video.id, label_class_id


def test_manual_tracks_interpolate_and_produce_research_analytics(
    client: TestClient,
) -> None:
    _project, video_id, label_class_id = _seed_video(client)
    first = client.post(
        f"/api/v1/videos/{video_id}/tracks",
        json={
            "video_id": video_id,
            "label_class_id": label_class_id,
            "track_number": 1,
            "keyframes": [
                {
                    "frame_index": 0,
                    "x_min": 0,
                    "y_min": 0,
                    "x_max": 10,
                    "y_max": 10,
                },
                {
                    "frame_index": 10,
                    "x_min": 10,
                    "y_min": 0,
                    "x_max": 20,
                    "y_max": 10,
                },
            ],
            "interpolation": "linear",
            "status": "verified",
        },
    )
    assert first.status_code == 201, first.text
    assert first.json()["metadata_json"]["source"] == "human"

    second = client.post(
        f"/api/v1/videos/{video_id}/tracks",
        json={
            "video_id": video_id,
            "label_class_id": label_class_id,
            "track_number": 2,
            "keyframes": [
                {
                    "frame_index": 0,
                    "x_min": 20,
                    "y_min": 0,
                    "x_max": 30,
                    "y_max": 10,
                },
                {
                    "frame_index": 10,
                    "x_min": 20,
                    "y_min": 10,
                    "x_max": 30,
                    "y_max": 20,
                },
            ],
            "interpolation": "linear",
            "status": "verified",
        },
    )
    assert second.status_code == 201, second.text

    calibration = client.put(
        f"/api/v1/videos/{video_id}/calibration",
        json={
            "distance_per_pixel": 0.1,
            "unit": "cm",
            "source": "tank ruler",
        },
    )
    assert calibration.status_code == 200, calibration.text

    analytics = client.post(
        f"/api/v1/videos/{video_id}/analytics",
        json={
            "zones": [
                {
                    "name": "left wall",
                    "x_min": 0,
                    "y_min": 0,
                    "x_max": 15,
                    "y_max": 100,
                }
            ],
            "heatmap_bins_x": 10,
            "heatmap_bins_y": 10,
            "activity_speed_threshold_pixels_per_second": 5,
        },
    )
    assert analytics.status_code == 200, analytics.text
    payload = analytics.json()
    assert payload["distance_per_pixel"] == pytest.approx(0.1)
    assert len(payload["tracks"]) == 2
    first_track = next(item for item in payload["tracks"] if item["tracker_id"] == 1)
    assert first_track["observed_frame_count"] == 11
    assert first_track["distance_pixels"] == pytest.approx(10)
    assert first_track["duration_seconds"] == pytest.approx(1)
    assert first_track["mean_speed_pixels_per_second"] == pytest.approx(10)
    assert first_track["distance_physical"] == pytest.approx(1)
    assert first_track["active_time_seconds"] == pytest.approx(1)
    assert first_track["inactive_time_seconds"] == pytest.approx(0)
    assert first_track["zone_time_seconds"]["left wall"] > 0
    assert payload["school_by_frame"][0]["active_track_count"] == 2
    assert payload["school_by_frame"][0]["mean_nearest_neighbor_pixels"] == pytest.approx(20)
    assert payload["heatmap"]
    assert sum(item["observation_count"] for item in payload["heatmap"]) == 22

    csv_export = client.get(f"/api/v1/videos/{video_id}/tracking-export?format=csv")
    assert csv_export.status_code == 200, csv_export.text
    assert "frame,time_seconds,tracker_id" in csv_export.text
    assert len(csv_export.text.strip().splitlines()) == 23

    mot_export = client.get(f"/api/v1/videos/{video_id}/tracking-export?format=mot")
    assert mot_export.status_code == 200, mot_export.text
    assert len(mot_export.text.strip().splitlines()) == 22

    json_export = client.get(f"/api/v1/videos/{video_id}/tracking-export?format=json")
    assert json_export.status_code == 200, json_export.text
    exported = json.loads(json_export.content)
    assert exported["format"] == "reefvision_video_tracks_v1"
    assert len(exported["tracks"]) == 2
    assert len(exported["tracks"][0]["interpolated_keyframes"]) == 11


def test_detector_tracking_job_is_queued_with_tracker_provenance(
    client: TestClient,
) -> None:
    project, video_id, label_class_id = _seed_video(client)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        model = ModelRegistration(
            project_id=str(project["id"]),
            purpose="detector",
            display_name="Fish detector",
            source_filename="fish.pt",
            managed_path=f"projects/{project['id']}/models/fish.pt",
            sha256="c" * 64,
            file_size_bytes=1,
            framework="ultralytics",
            task="detect",
            provider_name="ultralytics",
            provider_version="test",
            class_map_json={"mapping": {"fish": label_class_id}},
            metadata_json={},
        )
        session.add(model)
        session.commit()
        model_id = model.id

    response = client.post(
        f"/api/v1/videos/{video_id}/tracking-jobs",
        json={
            "model_id": model_id,
            "tracker": "botsort",
            "confidence_threshold": 0.3,
            "iou_threshold": 0.5,
            "every_n_frames": 2,
            "replace_generated_tracks": True,
        },
    )
    assert response.status_code == 201, response.text
    job = response.json()
    assert job["job_type"] == "video_track"
    assert job["status"] == "queued"
    assert job["request_json"]["tracker"] == "botsort"
    assert job["request_json"]["model_id"] == model_id
