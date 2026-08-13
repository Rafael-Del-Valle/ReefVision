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


def test_tracking_benchmark_ranks_candidates_against_the_same_ground_truth(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Tracker benchmark")
    video = _video(client, str(project["id"]), monkeypatch)
    classes = cast(list[dict[str, object]], project["label_classes"])
    label_class_id = str(classes[0]["id"])

    truth = _track(
        client,
        str(video["id"]),
        label_class_id,
        [
            {"frame": 0, "bbox": [10, 10, 20, 20]},
            {"frame": 2, "bbox": [10, 10, 20, 20]},
        ],
    )
    bytetrack = _track(
        client,
        str(video["id"]),
        label_class_id,
        [
            {"frame": 0, "bbox": [10, 10, 20, 20]},
            {"frame": 1, "bbox": [10, 10, 20, 20]},
            {"frame": 2, "bbox": [10, 10, 20, 20]},
        ],
    )
    botsort = _track(
        client,
        str(video["id"]),
        label_class_id,
        [
            {"frame": 0, "bbox": [10, 10, 20, 20]},
            {"frame": 1, "bbox": [70, 40, 10, 10]},
        ],
    )

    response = client.post(
        f"/api/v1/videos/{video['id']}/tracking-benchmark",
        json={
            "ground_truth_track_ids": [truth["id"]],
            "candidates": [
                {"name": "ByteTrack", "prediction_track_ids": [bytetrack["id"]]},
                {"name": "BoT-SORT", "prediction_track_ids": [botsort["id"]]},
            ],
            "iou_threshold": 0.5,
            "start_frame": 0,
            "end_frame": 2,
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["schema_version"] == "video-tracking-benchmark-0001"
    assert result["winner"] == "ByteTrack"
    assert [item["name"] for item in result["results"]] == ["ByteTrack", "BoT-SORT"]
    assert [item["rank"] for item in result["results"]] == [1, 2]

    best = result["results"][0]["evaluation"]
    assert best["recall"] == pytest.approx(1.0)
    assert best["precision"] == pytest.approx(1.0)
    assert best["mota"] == pytest.approx(1.0)

    second = result["results"][1]["evaluation"]
    assert second["recall"] == pytest.approx(1 / 3)
    assert second["precision"] == pytest.approx(0.5)
    assert second["missed_observations"] == 2
    assert second["false_positive_observations"] == 1
    assert second["mota"] == pytest.approx(0.0)


def test_tracking_benchmark_requires_unique_candidate_names(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Tracker benchmark validation")
    video = _video(client, str(project["id"]), monkeypatch)

    response = client.post(
        f"/api/v1/videos/{video['id']}/tracking-benchmark",
        json={
            "ground_truth_track_ids": ["truth"],
            "candidates": [
                {"name": "ByteTrack", "prediction_track_ids": ["a"]},
                {"name": "bytetrack", "prediction_track_ids": ["b"]},
            ],
        },
    )
    assert response.status_code == 422
