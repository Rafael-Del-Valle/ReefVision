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


def _create_track(
    client: TestClient,
    video_id: str,
    label_class_id: str,
    keyframes: list[dict[str, object]],
) -> str:
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
    return str(response.json()["id"])


def test_tracking_evaluation_reports_mot_style_errors(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Phase 6 tracking evaluation")
    monkeypatch.setattr(video_assets_module, "_inspect_video", _fake_metadata)
    imported = client.post(
        f"/api/v1/projects/{project['id']}/imports/videos",
        files={"file": ("fish.mp4", io.BytesIO(b"fake-video"), "video/mp4")},
    )
    assert imported.status_code == 201, imported.text
    video_id = str(imported.json()["id"])
    classes = cast(list[dict[str, object]], project["label_classes"])
    label_class_id = str(classes[0]["id"])

    ground_truth = _create_track(
        client,
        video_id,
        label_class_id,
        [
            {"frame": 0, "bbox": [10, 10, 20, 10]},
            {"frame": 3, "bbox": [40, 10, 20, 10]},
        ],
    )
    prediction_a = _create_track(
        client,
        video_id,
        label_class_id,
        [
            {"frame": 0, "bbox": [10, 10, 20, 10]},
            {"frame": 1, "bbox": [20, 10, 20, 10]},
        ],
    )
    prediction_b = _create_track(
        client,
        video_id,
        label_class_id,
        [{"frame": 3, "bbox": [40, 10, 20, 10]}],
    )
    false_prediction = _create_track(
        client,
        video_id,
        label_class_id,
        [{"frame": 0, "bbox": [70, 40, 10, 10]}],
    )

    response = client.post(
        f"/api/v1/videos/{video_id}/tracking-evaluation",
        json={
            "ground_truth_track_ids": [ground_truth],
            "prediction_track_ids": [
                prediction_a,
                prediction_b,
                false_prediction,
            ],
            "start_frame": 0,
            "end_frame": 3,
            "iou_threshold": 0.5,
            "class_aware": True,
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["ground_truth_observations"] == 4
    assert result["prediction_observations"] == 4
    assert result["matched_observations"] == 3
    assert result["missed_observations"] == 1
    assert result["false_positive_observations"] == 1
    assert result["missed_tracks"] == 0
    assert result["false_positive_tracks"] == 1
    assert result["tracking_recall"] == pytest.approx(0.75)
    assert result["tracking_precision"] == pytest.approx(0.75)
    assert result["id_switches"] == 1
    assert result["fragmentations"] == 1
    assert result["mean_iou"] == pytest.approx(1.0)
    assert result["mean_center_error_pixels"] == pytest.approx(0.0)
    assert result["mota"] == pytest.approx(0.25)
    assert result["per_ground_truth_track"][0]["id_switches"] == 1
    assert result["per_ground_truth_track"][0]["fragmentations"] == 1


def test_tracking_evaluation_rejects_overlapping_track_sets(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Phase 6 tracking validation")
    monkeypatch.setattr(video_assets_module, "_inspect_video", _fake_metadata)
    imported = client.post(
        f"/api/v1/projects/{project['id']}/imports/videos",
        files={"file": ("fish.mp4", io.BytesIO(b"fake-video"), "video/mp4")},
    )
    video_id = str(imported.json()["id"])
    classes = cast(list[dict[str, object]], project["label_classes"])
    track_id = _create_track(
        client,
        video_id,
        str(classes[0]["id"]),
        [{"frame": 0, "bbox": [10, 10, 20, 10]}],
    )

    response = client.post(
        f"/api/v1/videos/{video_id}/tracking-evaluation",
        json={
            "ground_truth_track_ids": [track_id],
            "prediction_track_ids": [track_id],
        },
    )
    assert response.status_code == 400
    assert "must not overlap" in response.json()["detail"]
