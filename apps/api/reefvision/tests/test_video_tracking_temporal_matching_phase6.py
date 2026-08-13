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
        "frame_count": 4,
        "fps": 10.0,
        "duration_seconds": 0.4,
    }


def _create_track(
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


def test_evaluation_preserves_valid_previous_frame_identity_in_ambiguous_overlap(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Temporal matching")
    monkeypatch.setattr(video_assets_module, "_inspect_video", _fake_metadata)
    imported = client.post(
        f"/api/v1/projects/{project['id']}/imports/videos",
        files={"file": ("crossing.mp4", io.BytesIO(b"video"), "video/mp4")},
    )
    assert imported.status_code == 201, imported.text
    video_id = str(imported.json()["id"])
    classes = cast(list[dict[str, object]], project["label_classes"])
    label_class_id = str(classes[0]["id"])

    truth_a = _create_track(
        client,
        video_id,
        label_class_id,
        [
            {"frame": 0, "bbox": [10, 10, 20, 20]},
            {"frame": 1, "bbox": [20, 10, 20, 20]},
        ],
    )
    truth_b = _create_track(
        client,
        video_id,
        label_class_id,
        [
            {"frame": 0, "bbox": [40, 10, 20, 20]},
            {"frame": 1, "bbox": [21, 10, 20, 20]},
        ],
    )
    prediction_a = _create_track(
        client,
        video_id,
        label_class_id,
        [
            {"frame": 0, "bbox": [10, 10, 20, 20]},
            {"frame": 1, "bbox": [21, 10, 20, 20]},
        ],
    )
    prediction_b = _create_track(
        client,
        video_id,
        label_class_id,
        [
            {"frame": 0, "bbox": [40, 10, 20, 20]},
            {"frame": 1, "bbox": [20, 10, 20, 20]},
        ],
    )

    response = client.post(
        f"/api/v1/videos/{video_id}/tracking-evaluation",
        json={
            "ground_truth_track_ids": [truth_a["id"], truth_b["id"]],
            "prediction_track_ids": [prediction_a["id"], prediction_b["id"]],
            "iou_threshold": 0.5,
            "start_frame": 0,
            "end_frame": 1,
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["matched_observations"] == 4
    assert result["id_switches"] == 0
    assert result["fragmentations"] == 0
    by_truth = {item["ground_truth_track_id"]: item for item in result["per_track"]}
    assert by_truth[truth_a["id"]]["matched_prediction_track_ids"] == [prediction_a["id"]]
    assert by_truth[truth_b["id"]]["matched_prediction_track_ids"] == [prediction_b["id"]]
