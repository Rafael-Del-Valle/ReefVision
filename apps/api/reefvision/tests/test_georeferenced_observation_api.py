from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.schemas.georeferenced_observation import (
    GeoReferencedObservation,
)
from reefvision.services import (
    video_assets as video_assets_module,
)
from reefvision.services.georeferenced_observations import (
    GeoReferencedObservationService,
)
from reefvision.tests.test_annotations import (
    create_project,
)


def _metadata(_path) -> dict[str, float | int]:
    return {
        "width_px": 100,
        "height_px": 60,
        "frame_count": 30,
        "fps": 10.0,
        "duration_seconds": 3.0,
    }


def _import_video(
    client: TestClient,
    project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    monkeypatch.setattr(
        video_assets_module,
        "_inspect_video",
        _metadata,
    )

    response = client.post(
        f"/api/v1/projects/{project_id}/imports/videos",
        files={
            "file": (
                "fish.mp4",
                io.BytesIO(b"fake-video"),
                "video/mp4",
            )
        },
    )

    assert response.status_code == 201, response.text

    return response.json()


def _payload(
    *,
    project_id: str,
    video_id: str,
    track_id: str,
    frame_index: int,
) -> GeoReferencedObservation:
    return GeoReferencedObservation.model_validate(
        {
            "id": uuid4(),
            "project_id": project_id,
            "video_asset_id": video_id,
            "detection_id": None,
            "track_id": track_id,
            "frame_index": frame_index,
            "frame_width_px": 100,
            "frame_height_px": 60,
            "bbox": {
                "x_min": 10.0 + frame_index,
                "y_min": 12.0,
                "x_max": 30.0 + frame_index,
                "y_max": 20.0,
            },
            "representative_pixel": {
                "x": 20.0 + frame_index,
                "y": 16.0,
                "method": "bbox_center",
            },
            "timestamp": {
                "frame_time_s": frame_index / 10.0,
                "utc": None,
                "source": "frame_index_fps",
                "fps": 10.0,
            },
            "pose": {
                "platform": {
                    "latitude_deg": 32.75,
                    "longitude_deg": -79.93,
                    "altitude_m": 100.0,
                    "altitude_datum": "relative_takeoff",
                    "height_above_surface_m": 105.0,
                    "yaw_deg": None,
                    "pitch_deg": None,
                    "roll_deg": None,
                    "heading_reference": "unknown",
                },
                "camera": {
                    "yaw_deg": 0.0,
                    "pitch_deg": -90.0,
                    "roll_deg": 0.0,
                    "orientation_source": ("gimbal_telemetry"),
                },
            },
            "calibration": {
                "calibration_id": ("sha256:" + ("b" * 64)),
                "calibration_version": "1",
                "checksum_sha256": "b" * 64,
                "camera_model": "test-camera",
                "image_width_px": 100,
                "image_height_px": 60,
                "focal_length_x_px": 50.0,
                "focal_length_y_px": 50.0,
                "principal_point_x_px": 50.0,
                "principal_point_y_px": 30.0,
                "distortion_model": "none",
                "zoom_state": 1.0,
            },
            "telemetry": {
                "source_id": "test.srt",
                "source_type": "dji_srt",
                "sample_index": frame_index,
                "synchronization_method": "nearest",
                "telemetry_time_s": (frame_index / 10.0),
                "telemetry_utc": None,
                "signed_time_delta_ms": 0.0,
                "absolute_time_error_ms": 0.0,
                "within_sync_tolerance": True,
                "sync_tolerance_ms": 100.0,
                "field_provenance": {
                    "position_source": "dji_srt",
                },
            },
            "location": {
                "latitude_deg": (32.75 + frame_index * 0.000001),
                "longitude_deg": (-79.93 + frame_index * 0.000001),
            },
            "uncertainty": {
                "available": False,
                "method": "not_estimated",
                "reason_unavailable": ("API integration test."),
            },
            "method": {
                "version": ("opencv-dji-enu-flat-wgs84-v1"),
                "surface_model": ("local_horizontal_plane"),
                "representative_pixel_policy_version": ("1.0.0"),
                "synchronization_version": ("nearest-frame-time-v1"),
                "pose_convention_version": ("absolute-gimbal-ned-to-enu-v1"),
            },
            "created_at": datetime.now(UTC),
        }
    )


def test_georeferenced_observation_read_routes(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(
        client,
        "Task 13 API",
    )

    video = _import_video(
        client,
        str(project["id"]),
        monkeypatch,
    )

    classes = cast(
        list[dict[str, object]],
        project["label_classes"],
    )

    track_response = client.post(
        f"/api/v1/videos/{video['id']}/tracks",
        json={
            "label_class_id": str(classes[0]["id"]),
            "keyframes": [
                {
                    "frame": 1,
                    "bbox": [11, 12, 20, 8],
                },
                {
                    "frame": 2,
                    "bbox": [12, 12, 20, 8],
                },
            ],
            "interpolation": "linear",
            "status": "verified",
        },
    )

    assert track_response.status_code == 201

    track_id = track_response.json()["id"]

    app = cast(FastAPI, client.app)

    observation_ids: list[str] = []

    with app.state.session_factory() as session:
        service = GeoReferencedObservationService(session)

        for frame_index in (1, 2):
            observation = _payload(
                project_id=str(project["id"]),
                video_id=str(video["id"]),
                track_id=track_id,
                frame_index=frame_index,
            )

            observation_ids.append(str(observation.id))

            service.persist(observation)

        session.commit()

    video_list = client.get(f"/api/v1/videos/{video['id']}/georeferenced-observations")

    assert video_list.status_code == 200
    assert video_list.json()["count"] == 2

    items = video_list.json()["items"]

    assert [item["frame_index"] for item in items] == [1, 2]

    assert items[0]["track_id"] == track_id
    assert items[0]["location"]["crs"] == "EPSG:4326"

    frame_filter = client.get(
        f"/api/v1/videos/{video['id']}/georeferenced-observations",
        params={"frame_index": 1},
    )

    assert frame_filter.status_code == 200
    assert frame_filter.json()["count"] == 1
    assert frame_filter.json()["items"][0]["frame_index"] == 1

    track_filter = client.get(
        f"/api/v1/videos/{video['id']}/georeferenced-observations",
        params={"track_id": track_id},
    )

    assert track_filter.status_code == 200
    assert track_filter.json()["count"] == 2

    track_list = client.get(f"/api/v1/video-tracks/{track_id}/georeferenced-observations")

    assert track_list.status_code == 200
    assert track_list.json()["count"] == 2

    frame_list = client.get(f"/api/v1/videos/{video['id']}/frames/1/georeferenced-observations")

    assert frame_list.status_code == 200
    assert frame_list.json()["count"] == 1

    detail = client.get(f"/api/v1/georeferenced-observations/{observation_ids[0]}")

    assert detail.status_code == 200

    payload = detail.json()

    assert payload["id"] == observation_ids[0]
    assert payload["video_asset_id"] == str(video["id"])
    assert payload["track_id"] == track_id
    assert payload["frame_index"] == 1
    assert payload["representative_pixel"]["method"] == "bbox_center"
    assert payload["telemetry"]["source_type"] == "dji_srt"
    assert payload["method"]["version"] == "opencv-dji-enu-flat-wgs84-v1"


def test_georeferenced_observation_read_route_errors(
    client: TestClient,
) -> None:
    missing_id = "00000000-0000-0000-0000-000000000001"

    detail = client.get(f"/api/v1/georeferenced-observations/{missing_id}")

    assert detail.status_code == 404

    video = client.get(f"/api/v1/videos/{missing_id}/georeferenced-observations")

    assert video.status_code == 404

    track = client.get(f"/api/v1/video-tracks/{missing_id}/georeferenced-observations")

    assert track.status_code == 404
