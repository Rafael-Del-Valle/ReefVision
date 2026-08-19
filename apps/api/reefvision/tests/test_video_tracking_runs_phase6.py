from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import Job, VideoTrack
from reefvision.services import video_assets as video_assets_module
from reefvision.tests.test_annotations import create_project


def _fake_metadata(_path: object) -> dict[str, float | int]:
    return {
        "width_px": 100,
        "height_px": 60,
        "frame_count": 10,
        "fps": 10.0,
        "duration_seconds": 1.0,
    }


def _video(
    client: TestClient,
    project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    monkeypatch.setattr(video_assets_module, "_inspect_video", _fake_metadata)
    response = client.post(
        f"/api/v1/projects/{project_id}/imports/videos",
        files={"file": ("runs.mp4", io.BytesIO(b"fake-video"), "video/mp4")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _track(
    client: TestClient,
    video_id: str,
    label_class_id: str,
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/videos/{video_id}/tracks",
        json={
            "label_class_id": label_class_id,
            "keyframes": [
                {"frame": 0, "bbox": [10, 10, 20, 20]},
                {"frame": 1, "bbox": [12, 10, 20, 20]},
            ],
            "interpolation": "linear",
            "status": "machine_generated",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_tracking_runs_include_zero_output_jobs_and_active_track_counts(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Tracking run summaries")
    video = _video(client, str(project["id"]), monkeypatch)
    label_classes = cast(list[dict[str, object]], project["label_classes"])
    track = _track(client, str(video["id"]), str(label_classes[0]["id"]))
    app = cast(FastAPI, client.app)
    completed = datetime.now(UTC)

    with app.state.session_factory() as session:
        bytetrack_job = Job(
            project_id=str(project["id"]),
            job_type="video_tracking",
            status="succeeded",
            request_json={
                "video_id": str(video["id"]),
                "model_id": "detector-a",
                "tracker": "bytetrack.yaml",
                "confidence": 0.2,
                "iou": 0.45,
                "device": "cpu",
                "minimum_track_frames": 2,
            },
            result_json={"unmapped_labels": ["unknown-fish"]},
            started_at=completed,
            completed_at=completed,
        )
        zero_job = Job(
            project_id=str(project["id"]),
            job_type="video_tracking",
            status="succeeded",
            request_json={
                "video_id": str(video["id"]),
                "model_id": "detector-a",
                "tracker": "botsort.yaml",
                "confidence": 0.25,
                "iou": 0.5,
                "device": "auto",
                "minimum_track_frames": 3,
            },
            result_json={"track_count": 0, "observation_count": 0},
            started_at=completed,
            completed_at=completed,
        )
        other_video_job = Job(
            project_id=str(project["id"]),
            job_type="video_tracking",
            status="succeeded",
            request_json={
                "video_id": "other-video",
                "model_id": "detector-a",
                "tracker": "bytetrack.yaml",
            },
        )
        session.add_all([bytetrack_job, zero_job, other_video_job])
        session.flush()
        stored_track = session.get(VideoTrack, str(track["id"]))
        assert stored_track is not None
        stored_track.source_job_id = bytetrack_job.id
        session.commit()
        bytetrack_job_id = bytetrack_job.id
        zero_job_id = zero_job.id

    response = client.get(f"/api/v1/videos/{video['id']}/tracking-runs")
    assert response.status_code == 200, response.text
    runs = {item["job_id"]: item for item in response.json()}
    assert set(runs) == {bytetrack_job_id, zero_job_id}

    bytetrack = runs[bytetrack_job_id]
    assert bytetrack["tracker"] == "bytetrack.yaml"
    assert bytetrack["model_id"] == "detector-a"
    assert bytetrack["confidence"] == pytest.approx(0.2)
    assert bytetrack["iou"] == pytest.approx(0.45)
    assert bytetrack["device"] == "cpu"
    assert bytetrack["minimum_track_frames"] == 2
    assert bytetrack["track_count"] == 1
    assert bytetrack["observation_count"] == 2
    assert bytetrack["unmapped_labels"] == ["unknown-fish"]

    zero = runs[zero_job_id]
    assert zero["tracker"] == "botsort.yaml"
    assert zero["track_count"] == 0
    assert zero["observation_count"] == 0
    assert zero["unmapped_labels"] == []


def test_tracking_runs_reject_unknown_video(client: TestClient) -> None:
    response = client.get("/api/v1/videos/00000000-0000-0000-0000-000000000000/tracking-runs")
    assert response.status_code == 404
