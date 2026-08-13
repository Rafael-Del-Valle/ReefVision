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
        files={"file": ("benchmark.mp4", io.BytesIO(b"fake-video"), "video/mp4")},
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


def test_tracking_evaluation_counts_misses_false_positives_switches_and_fragmentation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Tracking evaluation")
    video = _video(client, str(project["id"]), monkeypatch)
    classes = cast(list[dict[str, object]], project["label_classes"])
    label_class_id = str(classes[0]["id"])

    truth = _track(
        client,
        str(video["id"]),
        label_class_id,
        [
            {"frame": 0, "bbox": [10, 10, 20, 20]},
            {"frame": 3, "bbox": [10, 10, 20, 20]},
        ],
    )
    prediction_a = _track(
        client,
        str(video["id"]),
        label_class_id,
        [
            {"frame": 0, "bbox": [10, 10, 20, 20]},
            {"frame": 1, "bbox": [10, 10, 20, 20]},
        ],
    )
    prediction_b = _track(
        client,
        str(video["id"]),
        label_class_id,
        [{"frame": 3, "bbox": [10, 10, 20, 20]}],
    )
    false_positive = _track(
        client,
        str(video["id"]),
        label_class_id,
        [{"frame": 2, "bbox": [70, 40, 10, 10]}],
    )

    response = client.post(
        f"/api/v1/videos/{video['id']}/tracking-evaluation",
        json={
            "ground_truth_track_ids": [truth["id"]],
            "prediction_track_ids": [
                prediction_a["id"],
                prediction_b["id"],
                false_positive["id"],
            ],
            "iou_threshold": 0.5,
            "class_aware": True,
            "start_frame": 0,
            "end_frame": 3,
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["schema_version"] == "video-tracking-evaluation-0001"
    assert result["ground_truth_observations"] == 4
    assert result["prediction_observations"] == 4
    assert result["matched_observations"] == 3
    assert result["missed_observations"] == 1
    assert result["false_positive_observations"] == 1
    assert result["recall"] == pytest.approx(0.75)
    assert result["precision"] == pytest.approx(0.75)
    assert result["missed_tracks"] == 0
    assert result["false_positive_tracks"] == 1
    assert result["id_switches"] == 1
    assert result["fragmentations"] == 1
    assert result["mean_iou"] == pytest.approx(1.0)
    assert result["mean_center_error_pixels"] == pytest.approx(0.0)
    assert result["mota"] == pytest.approx(0.25)

    track_result = result["per_track"][0]
    assert track_result["ground_truth_track_id"] == truth["id"]
    assert track_result["matched_observations"] == 3
    assert track_result["missed_observations"] == 1
    assert track_result["id_switches"] == 1
    assert track_result["fragmentations"] == 1
    assert set(track_result["matched_prediction_track_ids"]) == {
        prediction_a["id"],
        prediction_b["id"],
    }


def test_tracking_evaluation_rejects_invalid_track_sets(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Tracking evaluation validation")
    video = _video(client, str(project["id"]), monkeypatch)
    classes = cast(list[dict[str, object]], project["label_classes"])
    label_class_id = str(classes[0]["id"])
    truth = _track(
        client,
        str(video["id"]),
        label_class_id,
        [{"frame": 0, "bbox": [10, 10, 20, 20]}],
    )

    overlap = client.post(
        f"/api/v1/videos/{video['id']}/tracking-evaluation",
        json={
            "ground_truth_track_ids": [truth["id"]],
            "prediction_track_ids": [truth["id"]],
        },
    )
    assert overlap.status_code == 422

    outside_range = client.post(
        f"/api/v1/videos/{video['id']}/tracking-evaluation",
        json={
            "ground_truth_track_ids": [truth["id"]],
            "prediction_track_ids": ["00000000-0000-0000-0000-000000000000"],
            "start_frame": 0,
            "end_frame": 99,
        },
    )
    assert outside_range.status_code == 422
