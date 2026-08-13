from __future__ import annotations

import io
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
        files={"file": ("fish.mp4", io.BytesIO(b"fake-video"), "video/mp4")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _track(
    client: TestClient,
    video_id: str,
    label_class_id: str,
    keyframes: list[dict[str, object]],
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/videos/{video_id}/tracks",
        json={
            "label_class_id": label_class_id,
            "keyframes": keyframes,
            "interpolation": "linear",
            "status": "verified",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_benchmark_resolves_prediction_tracks_from_tracking_job(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Job-resolved tracker benchmark")
    video = _video(client, str(project["id"]), monkeypatch)
    classes = cast(list[dict[str, object]], project["label_classes"])
    label_class_id = str(classes[0]["id"])

    truth = _track(
        client,
        str(video["id"]),
        label_class_id,
        [
            {"frame": 0, "bbox": [10, 10, 20, 20]},
            {"frame": 1, "bbox": [10, 10, 20, 20]},
        ],
    )
    good = _track(
        client,
        str(video["id"]),
        label_class_id,
        [
            {"frame": 0, "bbox": [10, 10, 20, 20]},
            {"frame": 1, "bbox": [10, 10, 20, 20]},
        ],
    )
    poor = _track(
        client,
        str(video["id"]),
        label_class_id,
        [{"frame": 0, "bbox": [70, 40, 10, 10]}],
    )

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        job = Job(
            project_id=str(project["id"]),
            job_type="video_tracking",
            status="succeeded",
            request_json={
                "video_id": str(video["id"]),
                "tracker": "bytetrack.yaml",
                "model_id": "model-123",
                "confidence": 0.2,
                "iou": 0.4,
                "device": "cpu",
                "minimum_track_frames": 2,
            },
        )
        session.add(job)
        session.flush()
        track = session.get(VideoTrack, str(good["id"]))
        assert track is not None
        track.source_job_id = job.id
        session.commit()
        job_id = job.id

    response = client.post(
        f"/api/v1/videos/{video['id']}/tracking-benchmark",
        json={
            "ground_truth_track_ids": [truth["id"]],
            "candidates": [
                {"name": "ByteTrack", "source_job_id": job_id},
                {"name": "BoT-SORT", "prediction_track_ids": [poor["id"]]},
            ],
            "start_frame": 0,
            "end_frame": 1,
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["winner"] == "ByteTrack"
    assert result["ground_truth_track_ids"] == [truth["id"]]
    assert result["start_frame"] == 0
    assert result["end_frame"] == 1
    assert result["iou_threshold"] == pytest.approx(0.5)
    assert result["class_aware"] is True

    byte_result = result["results"][0]
    assert byte_result["source_job_id"] == job_id
    assert byte_result["prediction_track_ids"] == [good["id"]]
    assert byte_result["tracker"] == "bytetrack.yaml"
    assert byte_result["model_id"] == "model-123"
    assert byte_result["job_status"] == "succeeded"
    assert byte_result["tracking_settings"] == {
        "tracker": "bytetrack.yaml",
        "model_id": "model-123",
        "confidence": 0.2,
        "iou": 0.4,
        "device": "cpu",
        "minimum_track_frames": 2,
    }
    assert byte_result["evaluation"]["mota"] == pytest.approx(1.0)


def test_benchmark_scores_succeeded_job_with_zero_prediction_tracks(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Zero-output tracker benchmark")
    video = _video(client, str(project["id"]), monkeypatch)
    classes = cast(list[dict[str, object]], project["label_classes"])
    label_class_id = str(classes[0]["id"])
    truth = _track(
        client,
        str(video["id"]),
        label_class_id,
        [{"frame": 0, "bbox": [10, 10, 20, 20]}],
    )
    perfect = _track(
        client,
        str(video["id"]),
        label_class_id,
        [{"frame": 0, "bbox": [10, 10, 20, 20]}],
    )

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        job = Job(
            project_id=str(project["id"]),
            job_type="video_tracking",
            status="succeeded",
            request_json={
                "video_id": str(video["id"]),
                "tracker": "botsort.yaml",
                "model_id": "model-zero",
            },
            result_json={"track_count": 0, "observation_count": 0},
        )
        session.add(job)
        session.commit()
        job_id = job.id

    response = client.post(
        f"/api/v1/videos/{video['id']}/tracking-benchmark",
        json={
            "ground_truth_track_ids": [truth["id"]],
            "candidates": [
                {"name": "Zero output", "source_job_id": job_id},
                {"name": "Perfect", "prediction_track_ids": [perfect["id"]]},
            ],
            "start_frame": 0,
            "end_frame": 0,
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    zero_result = next(item for item in result["results"] if item["name"] == "Zero output")
    evaluation = zero_result["evaluation"]
    assert zero_result["prediction_track_ids"] == []
    assert evaluation["prediction_track_count"] == 0
    assert evaluation["prediction_observations"] == 0
    assert evaluation["matched_observations"] == 0
    assert evaluation["missed_observations"] == 1
    assert evaluation["recall"] == pytest.approx(0.0)
    assert evaluation["precision"] == pytest.approx(0.0)
    assert evaluation["mota"] == pytest.approx(0.0)


def test_benchmark_rejects_wrong_video_and_incomplete_tracking_jobs(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Tracking job validation")
    first_video = _video(client, str(project["id"]), monkeypatch)
    second_video = _video(client, str(project["id"]), monkeypatch)
    app = cast(FastAPI, client.app)

    with app.state.session_factory() as session:
        wrong_video_job = Job(
            project_id=str(project["id"]),
            job_type="video_tracking",
            status="succeeded",
            request_json={
                "video_id": str(second_video["id"]),
                "tracker": "botsort.yaml",
            },
        )
        incomplete_job = Job(
            project_id=str(project["id"]),
            job_type="video_tracking",
            status="running",
            request_json={
                "video_id": str(first_video["id"]),
                "tracker": "bytetrack.yaml",
            },
        )
        session.add_all([wrong_video_job, incomplete_job])
        session.commit()
        wrong_video_job_id = wrong_video_job.id
        incomplete_job_id = incomplete_job.id

    wrong_video = client.post(
        f"/api/v1/videos/{first_video['id']}/tracking-benchmark",
        json={
            "ground_truth_track_ids": ["truth"],
            "candidates": [
                {"name": "Wrong video", "source_job_id": wrong_video_job_id},
                {"name": "Other", "prediction_track_ids": ["prediction"]},
            ],
        },
    )
    assert wrong_video.status_code == 422

    incomplete = client.post(
        f"/api/v1/videos/{first_video['id']}/tracking-benchmark",
        json={
            "ground_truth_track_ids": ["truth"],
            "candidates": [
                {"name": "Incomplete", "source_job_id": incomplete_job_id},
                {"name": "Other", "prediction_track_ids": ["prediction"]},
            ],
        },
    )
    assert incomplete.status_code == 422
