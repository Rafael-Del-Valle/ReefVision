from __future__ import annotations

import io
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import ModelRegistration
from reefvision.jobs import video_tracking as tracking_module
from reefvision.ml.video_tracking import TrackObservation
from reefvision.services import video_assets as video_assets_module
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project


class FakeVideoTrackingProvider:
    provider_id = "ultralytics"

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
        assert tracker == "bytetrack.yaml"
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

    classes = cast(list[dict[str, object]], project["label_classes"])
    track = client.post(
        f"/api/v1/videos/{video['id']}/tracks",
        json={
            "label_class_id": str(classes[0]["id"]),
            "keyframes": [
                {"frame": 0, "bbox": [10, 10, 20, 10]},
                {"frame": 10, "bbox": [30, 10, 20, 10]},
            ],
            "interpolation": "linear",
            "status": "verified",
        },
    )
    assert track.status_code == 201, track.text
    track_payload = track.json()
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


def test_fake_detector_tracker_creates_editable_machine_track(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Phase 6 tracker")
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
        lambda _name: FakeVideoTrackingProvider(),
    )
    queued = client.post(
        f"/api/v1/videos/{video['id']}/tracking-jobs",
        json={
            "model_id": model_id,
            "tracker": "bytetrack.yaml",
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
