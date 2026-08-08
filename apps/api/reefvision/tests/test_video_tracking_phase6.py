from __future__ import annotations

import io
import json
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import ModelRegistration
from reefvision.jobs import video as video_job_module
from reefvision.jobs import video_tracking as tracking_module
from reefvision.ml.video_tracking import TrackObservation
from reefvision.services import video_assets as video_assets_module
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project


class FakeVideoTrackingProvider:
    provider_id = "ultralytics"

    def __init__(self, expected_tracker: str) -> None:
        self.expected_tracker = expected_tracker

    @property
    def provider_version(self) -> str:
        return "test-tracker"

    def track(
        self,
        checkpoint_path: Path,
        video_path: Path,
        *,
        tracker: str,
        confidence: float,
        iou: float,
        device: str,
    ) -> list[TrackObservation]:
        assert checkpoint_path.read_bytes() == b"fake-detector"
        assert video_path.read_bytes() == b"fake-video"
        assert tracker == self.expected_tracker
        assert confidence == pytest.approx(0.2)
        assert iou == pytest.approx(0.4)
        assert device == "cpu"
        return [
            TrackObservation(
                frame=0,
                provider_track_id=7,
                class_name="fish",
                confidence=0.9,
                bbox=(10, 10, 20, 10),
            ),
            TrackObservation(
                frame=1,
                provider_track_id=7,
                class_name="fish",
                confidence=0.8,
                bbox=(20, 10, 20, 10),
            ),
            TrackObservation(
                frame=2,
                provider_track_id=7,
                class_name="fish",
                confidence=0.85,
                bbox=(30, 10, 20, 10),
            ),
        ]


class FakeCapture:
    def __init__(self, frame_count: int) -> None:
        self.frame_count = frame_count
        self.index = 0

    def isOpened(self) -> bool:
        return True

    def read(self) -> tuple[bool, object | None]:
        if self.index >= self.frame_count:
            return False, None
        self.index += 1
        return True, object()

    def release(self) -> None:
        return None


def _fake_metadata(_path: Path) -> dict[str, float | int]:
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
    monkeypatch.setattr(video_assets_module, "_inspect_video", _fake_metadata)
    response = client.post(
        f"/api/v1/projects/{project_id}/imports/videos",
        files={"file": ("fish.mp4", io.BytesIO(b"fake-video"), "video/mp4")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_track(
    client: TestClient,
    video_id: str,
    label_class_id: str,
    *,
    y: float,
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/videos/{video_id}/tracks",
        json={
            "label_class_id": label_class_id,
            "keyframes": [
                {"frame": 0, "bbox": [10, y, 20, 10]},
                {"frame": 10, "bbox": [30, y, 20, 10]},
            ],
            "interpolation": "linear",
            "status": "verified",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_managed_video_import_extraction_and_track_analytics(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Phase 6 managed video")
    video = _import_video(client, str(project["id"]), monkeypatch)
    assert video["frame_count"] == 30
    assert video["fps"] == pytest.approx(10.0)
    assert video["status"] == "imported"

    extraction = client.post(
        f"/api/v1/videos/{video['id']}/extract",
        json={"every_n_frames": 5},
    )
    assert extraction.status_code == 200, extraction.text
    queued = client.get(f"/api/v1/videos/{video['id']}")
    assert queued.status_code == 200, queued.text
    assert queued.json()["status"] == "extracting"
    assert queued.json()["extraction_job_id"] == extraction.json()["id"]

    app = cast(FastAPI, client.app)
    monkeypatch.setattr(
        video_job_module.cv2,
        "VideoCapture",
        lambda _path: FakeCapture(30),
    )

    def fake_imwrite(path: str, _frame: object) -> bool:
        Path(path).write_bytes(b"fake-jpeg")
        return True

    monkeypatch.setattr(video_job_module.cv2, "imwrite", fake_imwrite)
    assert video_job_module.process_video_extract_job(
        app.state.settings,
        app.state.session_factory,
        extraction.json()["id"],
    )
    extracted = client.get(f"/api/v1/videos/{video['id']}")
    assert extracted.status_code == 200, extracted.text
    assert extracted.json()["status"] == "frames_ready"
    frame = client.get(f"/api/v1/videos/{video['id']}/frames/10")
    assert frame.status_code == 200, frame.text
    assert frame.content == b"fake-jpeg"
    skipped = client.get(f"/api/v1/videos/{video['id']}/frames/11")
    assert skipped.status_code == 404

    classes = cast(list[dict[str, object]], project["label_classes"])
    track_payload = _create_track(
        client,
        str(video["id"]),
        str(classes[0]["id"]),
        y=10,
    )
    assert track_payload["revision"] == 1

    interpolation = client.get(f"/api/v1/video-tracks/{track_payload['id']}/interpolation")
    assert interpolation.status_code == 200, interpolation.text
    frames = interpolation.json()["frames"]
    assert len(frames) == 11
    assert frames[5]["bbox"] == pytest.approx([20, 10, 20, 10])
    assert frames[5]["source"] == "interpolated"

    analytics = client.get(f"/api/v1/video-tracks/{track_payload['id']}/analytics")
    assert analytics.status_code == 200, analytics.text
    summary = analytics.json()
    assert summary["duration_seconds"] == pytest.approx(1.0)
    assert summary["path_length_pixels"] == pytest.approx(20.0)
    assert summary["mean_speed_pixels_per_second"] == pytest.approx(20.0)
    assert sum(summary["occupancy_grid"].values()) == 11

    stale = client.put(
        f"/api/v1/video-tracks/{track_payload['id']}",
        json={
            "base_revision": 0,
            "label_class_id": str(classes[0]["id"]),
            "keyframes": [{"frame": 0, "bbox": [10, 10, 20, 10]}],
            "interpolation": "hold",
            "status": "verified",
        },
    )
    assert stale.status_code == 422


def test_behavior_analytics_calibration_and_research_exports(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Phase 6 behavior analytics")
    video = _import_video(client, str(project["id"]), monkeypatch)
    classes = cast(list[dict[str, object]], project["label_classes"])
    label_class_id = str(classes[0]["id"])
    first = _create_track(client, str(video["id"]), label_class_id, y=10)
    second = _create_track(client, str(video["id"]), label_class_id, y=30)

    calibration = client.put(
        f"/api/v1/videos/{video['id']}/calibration",
        json={
            "distance_per_pixel": 0.5,
            "unit": "cm",
            "source": "test ruler",
        },
    )
    assert calibration.status_code == 200, calibration.text
    assert calibration.json()["revision"] == video["revision"] + 3
    assert calibration.json()["metadata_json"]["calibration"]["distance_per_pixel"] == 0.5

    behavior = client.post(
        f"/api/v1/videos/{video['id']}/analytics",
        json={
            "zones": [
                {
                    "name": "whole frame",
                    "x_min": 0,
                    "y_min": 0,
                    "x_max": 100,
                    "y_max": 60,
                }
            ],
            "heatmap_bins_x": 5,
            "heatmap_bins_y": 3,
            "activity_speed_threshold_pixels_per_second": 15,
        },
    )
    assert behavior.status_code == 200, behavior.text
    payload = behavior.json()
    assert payload["warnings"] == []
    assert payload["distance_per_pixel"] == pytest.approx(0.5)
    assert payload["physical_unit"] == "cm"
    assert len(payload["tracks"]) == 2
    by_track = {item["track_id"]: item for item in payload["tracks"]}
    for track_id in (first["id"], second["id"]):
        result = by_track[track_id]
        assert result["distance_pixels"] == pytest.approx(20.0)
        assert result["mean_speed_pixels_per_second"] == pytest.approx(20.0)
        assert result["active_time_seconds"] == pytest.approx(1.0)
        assert result["inactive_time_seconds"] == pytest.approx(0.0)
        assert result["distance_physical"] == pytest.approx(10.0)
        assert result["mean_speed_physical_per_second"] == pytest.approx(10.0)
        assert result["zone_time_seconds"]["whole frame"] == pytest.approx(1.1)

    school = payload["school_by_frame"]
    assert len(school) == 11
    assert school[0]["active_track_count"] == 2
    assert school[0]["mean_nearest_neighbor_pixels"] == pytest.approx(20.0)
    assert school[0]["school_spread_pixels"] == pytest.approx(10.0)
    assert school[0]["mean_nearest_neighbor_physical"] == pytest.approx(10.0)
    assert sum(item["observation_count"] for item in payload["heatmap"]) == 22

    csv_export = client.get(f"/api/v1/videos/{video['id']}/exports/csv")
    assert csv_export.status_code == 200, csv_export.text
    csv_lines = csv_export.text.strip().splitlines()
    assert len(csv_lines) == 23
    assert csv_lines[0].startswith("frame,time_seconds,track_number")

    mot_export = client.get(f"/api/v1/videos/{video['id']}/exports/mot")
    assert mot_export.status_code == 200, mot_export.text
    mot_lines = mot_export.text.strip().splitlines()
    assert len(mot_lines) == 22
    assert mot_lines[0].startswith("1,1,")

    json_export = client.get(f"/api/v1/videos/{video['id']}/exports/json")
    assert json_export.status_code == 200, json_export.text
    exported = json.loads(json_export.content)
    assert exported["format"] == "reefvision_video_tracks_v1"
    assert exported["video"]["sha256"] == video["sha256"]
    assert len(exported["tracks"]) == 2
    assert len(exported["tracks"][0]["interpolated_frames"]) == 11


@pytest.mark.parametrize("tracker", ["bytetrack.yaml", "botsort.yaml"])
def test_fake_detector_tracker_creates_editable_machine_track(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tracker: str,
) -> None:
    project = create_project(client, f"Phase 6 tracker {tracker}")
    video = _import_video(client, str(project["id"]), monkeypatch)
    classes = cast(list[dict[str, object]], project["label_classes"])
    label_class_id = str(classes[0]["id"])
    app = cast(FastAPI, client.app)
    model_id = "b4c0e265-28f4-43c8-bda8-1d73d48ff34b"
    managed_relative = f"{project['storage_root']}/models/{model_id}.pt"
    managed_path = resolve_managed_project_path(app.state.settings, managed_relative)
    managed_path.parent.mkdir(parents=True, exist_ok=True)
    managed_path.write_bytes(b"fake-detector")
    with app.state.session_factory() as session:
        session.add(
            ModelRegistration(
                id=model_id,
                project_id=str(project["id"]),
                purpose="detector",
                display_name="Fish detector",
                source_filename="fish.pt",
                managed_path=managed_relative,
                sha256="a" * 64,
                file_size_bytes=len(b"fake-detector"),
                framework="ultralytics",
                task="detect",
                provider_name="ultralytics",
                provider_version="test",
                class_map_json={"labels": ["fish"], "mapping": {"fish": label_class_id}},
                input_size_json={"width": 640, "height": 640},
                metadata_json={},
            )
        )
        session.commit()

    monkeypatch.setattr(
        tracking_module,
        "video_tracking_provider_for_name",
        lambda _name: FakeVideoTrackingProvider(tracker),
    )
    queued = client.post(
        f"/api/v1/videos/{video['id']}/tracking-jobs",
        json={
            "model_id": model_id,
            "tracker": tracker,
            "confidence": 0.2,
            "iou": 0.4,
            "device": "cpu",
            "minimum_track_frames": 2,
        },
    )
    assert queued.status_code == 200, queued.text
    assert tracking_module.process_video_tracking_job(
        app.state.settings,
        app.state.session_factory,
        queued.json()["id"],
    )
    tracks = client.get(f"/api/v1/videos/{video['id']}/tracks")
    assert tracks.status_code == 200, tracks.text
    job_id = queued.json()["id"]
    machine_tracks = [item for item in tracks.json() if item["source_job_id"] == job_id]
    assert len(machine_tracks) == 1
    machine = machine_tracks[0]
    assert machine["source_model_id"] == model_id
    assert machine["status"] == "machine_generated"
    assert len(machine["keyframes_json"]) == 3
    assert machine["metadata_json"]["provider_track_id"] == 7
    assert machine["metadata_json"]["tracker"] == tracker
    assert machine["metadata_json"]["model_sha256"] == "a" * 64
    assert machine["metadata_json"]["source_video_sha256"] == video["sha256"]
    assert machine["metadata_json"]["confidence_threshold"] == pytest.approx(0.2)
    assert machine["metadata_json"]["iou_threshold"] == pytest.approx(0.4)

    updated = client.put(
        f"/api/v1/video-tracks/{machine['id']}",
        json={
            "base_revision": machine["revision"],
            "label_class_id": label_class_id,
            "keyframes": machine["keyframes_json"],
            "interpolation": "linear",
            "status": "verified",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["revision"] == machine["revision"] + 1
    assert updated.json()["status"] == "verified"


def test_video_tracking_rejects_unknown_tracker(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Phase 6 tracker validation")
    video = _import_video(client, str(project["id"]), monkeypatch)
    response = client.post(
        f"/api/v1/videos/{video['id']}/tracking-jobs",
        json={
            "model_id": "not-a-real-model",
            "tracker": "unknown.yaml",
        },
    )
    assert response.status_code == 422
