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


def test_direct_tracking_evaluation_scores_empty_prediction_set(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Zero-prediction evaluation")
    monkeypatch.setattr(video_assets_module, "_inspect_video", _fake_metadata)
    imported = client.post(
        f"/api/v1/projects/{project['id']}/imports/videos",
        files={"file": ("fish.mp4", io.BytesIO(b"video"), "video/mp4")},
    )
    assert imported.status_code == 201, imported.text
    video_id = str(imported.json()["id"])
    classes = cast(list[dict[str, object]], project["label_classes"])

    truth = client.post(
        f"/api/v1/videos/{video_id}/tracks",
        json={
            "label_class_id": str(classes[0]["id"]),
            "keyframes": [
                {"frame": 0, "bbox": [10, 10, 20, 10]},
                {"frame": 2, "bbox": [14, 10, 20, 10]},
            ],
            "interpolation": "linear",
            "status": "verified",
        },
    )
    assert truth.status_code == 201, truth.text

    response = client.post(
        f"/api/v1/videos/{video_id}/tracking-evaluation",
        json={
            "ground_truth_track_ids": [truth.json()["id"]],
            "prediction_track_ids": [],
            "start_frame": 0,
            "end_frame": 2,
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["prediction_track_count"] == 0
    assert result["prediction_observations"] == 0
    assert result["matched_observations"] == 0
    assert result["ground_truth_observations"] == 3
    assert result["missed_observations"] == 3
    assert result["false_positive_observations"] == 0
    assert result["recall"] == pytest.approx(0.0)
    assert result["precision"] == pytest.approx(0.0)
    assert result["missed_tracks"] == 1
    assert result["false_positive_tracks"] == 0
    assert result["id_switches"] == 0
    assert result["fragmentations"] == 0
    assert result["mota"] == pytest.approx(0.0)
