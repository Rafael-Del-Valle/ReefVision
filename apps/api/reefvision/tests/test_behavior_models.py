from __future__ import annotations

import io
from typing import cast

import pytest
from fastapi.testclient import TestClient

from reefvision.services import video_assets as video_assets_module
from reefvision.tests.test_annotations import create_project


def _fake_metadata(_path: object) -> dict[str, float | int]:
    return {
        "width_px": 200,
        "height_px": 100,
        "frame_count": 8,
        "fps": 10.0,
        "duration_seconds": 0.8,
    }


def _keyframes(xs: list[float]) -> list[dict[str, object]]:
    return [
        {
            "frame": frame,
            "bbox": [x, 10, 40, 20],
        }
        for frame, x in enumerate(xs)
    ]


def _setup(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    project = create_project(client, "Behavior model workflow")
    monkeypatch.setattr(video_assets_module, "_inspect_video", _fake_metadata)
    video_response = client.post(
        f"/api/v1/projects/{project['id']}/imports/videos",
        files={"file": ("behavior-model.mp4", io.BytesIO(b"video"), "video/mp4")},
    )
    assert video_response.status_code == 201, video_response.text
    video = video_response.json()
    classes = cast(list[dict[str, object]], project["label_classes"])
    label_class_id = str(classes[0]["id"])

    labeled = client.post(
        f"/api/v1/videos/{video['id']}/tracks",
        json={
            "track_number": 1,
            "label_class_id": label_class_id,
            "keyframes": _keyframes([0, 0, 10, 20, 20, 20, 30, 40]),
            "interpolation": "linear",
            "status": "verified",
        },
    )
    assert labeled.status_code == 201, labeled.text

    inference = client.post(
        f"/api/v1/videos/{video['id']}/tracks",
        json={
            "track_number": 2,
            "label_class_id": label_class_id,
            "keyframes": _keyframes([0, 10, 20, 30, 40, 50, 60, 70]),
            "interpolation": "linear",
            "status": "verified",
        },
    )
    assert inference.status_code == 201, inference.text
    return project, video, labeled.json(), inference.json()


def _ethogram(client: TestClient, project_id: str) -> dict[str, object]:
    response = client.post(
        f"/api/v1/projects/{project_id}/behavior-ethograms",
        json={
            "name": "Locomotion",
            "states": [
                {"code": "rest", "label": "Rest", "channel": "locomotion"},
                {"code": "swim", "label": "Swimming", "channel": "locomotion"},
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _label_training_bouts(
    client: TestClient,
    track_id: str,
    ethogram: dict[str, object],
) -> None:
    states = {
        item["code"]: item
        for item in cast(list[dict[str, object]], ethogram["states"])
    }
    for code, start, end in (
        ("rest", 0, 1),
        ("swim", 2, 3),
        ("rest", 4, 5),
        ("swim", 6, 7),
    ):
        response = client.post(
            f"/api/v1/video-tracks/{track_id}/behavior-bouts",
            json={
                "ethogram_revision_id": ethogram["id"],
                "behavior_state_id": states[code]["id"],
                "start_frame": start,
                "end_frame": end,
                "source": "manual",
            },
        )
        assert response.status_code == 201, response.text


def _train(
    client: TestClient,
    project_id: str,
    track_id: str,
    ethogram: dict[str, object],
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/projects/{project_id}/behavior-models",
        json={
            "ethogram_revision_id": ethogram["id"],
            "channel": "locomotion",
            "display_name": "Transparent locomotion model",
            "feature_preset": "track_only",
            "track_ids": [track_id],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_behavior_model_prediction_review_and_export_workflow(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, _video, labeled, inference = _setup(client, monkeypatch)
    ethogram = _ethogram(client, str(project["id"]))
    _label_training_bouts(client, str(labeled["id"]), ethogram)

    model = _train(
        client,
        str(project["id"]),
        str(labeled["id"]),
        ethogram,
    )
    assert model["algorithm"] == "standardized_nearest_centroid"
    assert model["feature_set_version"] == "reefvision-behavior-features-0001"
    assert model["training_sample_count"] == 4
    assert sorted(model["class_counts"].values()) == [2, 2]
    assert len(model["training_manifest_sha256"]) == 64

    listed_models = client.get(
        f"/api/v1/projects/{project['id']}/behavior-models",
        params={"ethogram_revision_id": ethogram["id"]},
    )
    assert listed_models.status_code == 200, listed_models.text
    assert [item["id"] for item in listed_models.json()] == [model["id"]]

    run = client.post(
        f"/api/v1/video-tracks/{inference['id']}/behavior-predictions",
        json={
            "model_id": model["id"],
            "window_frames": 4,
            "stride_frames": 4,
        },
    )
    assert run.status_code == 200, run.text
    run_payload = run.json()
    assert run_payload["prediction_count"] == 2
    assert run_payload["source_track_revision"] == inference["revision"]
    predictions = run_payload["predictions"]
    assert all(item["review_status"] == "pending" for item in predictions)
    assert all(
        item["score_semantics"]
        == "normalized_inverse_distance_not_calibrated"
        for item in predictions
    )
    assert all(0 <= item["prediction_score"] <= 1 for item in predictions)

    accepted = client.put(
        f"/api/v1/behavior-predictions/{predictions[0]['id']}/review",
        json={"action": "accept"},
    )
    assert accepted.status_code == 200, accepted.text
    accepted_payload = accepted.json()
    assert accepted_payload["review_status"] == "accepted"
    assert accepted_payload["accepted_bout_series_id"]

    accepted_again = client.put(
        f"/api/v1/behavior-predictions/{predictions[0]['id']}/review",
        json={"action": "accept"},
    )
    assert accepted_again.status_code == 200, accepted_again.text
    assert (
        accepted_again.json()["accepted_bout_series_id"]
        == accepted_payload["accepted_bout_series_id"]
    )

    rejected = client.put(
        f"/api/v1/behavior-predictions/{predictions[1]['id']}/review",
        json={"action": "reject"},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["review_status"] == "rejected"

    bouts = client.get(
        f"/api/v1/video-tracks/{inference['id']}/behavior-bouts",
        params={"ethogram_revision_id": ethogram["id"]},
    )
    assert bouts.status_code == 200, bouts.text
    accepted_bouts = bouts.json()
    assert len(accepted_bouts) == 1
    bout = accepted_bouts[0]
    assert bout["source"] == "accepted_prediction"
    assert bout["review_status"] == "verified"
    assert bout["source_behavior_classifier_id"] == model["id"]
    assert bout["source_behavior_prediction_id"] == predictions[0]["id"]

    # Accepted predictions are canonical after review but are not silently
    # promoted to manual training truth.
    retrain = client.post(
        f"/api/v1/projects/{project['id']}/behavior-models",
        json={
            "ethogram_revision_id": ethogram["id"],
            "channel": "locomotion",
            "display_name": "Should not self train",
            "feature_preset": "track_only",
            "track_ids": [inference["id"]],
        },
    )
    assert retrain.status_code == 400, retrain.text
    assert "verified manual bouts" in retrain.json()["detail"]

    json_export = client.get(
        f"/api/v1/video-tracks/{inference['id']}/behavior-export",
        params={
            "ethogram_revision_id": ethogram["id"],
            "format": "json",
            "model_id": model["id"],
        },
    )
    assert json_export.status_code == 200, json_export.text
    document = json_export.json()
    assert document["provenance"]["model"]["id"] == model["id"]
    assert len(document["bouts"]) == 1
    assert len(document["predictions"]) == 2

    bouts_csv = client.get(
        f"/api/v1/video-tracks/{inference['id']}/behavior-export",
        params={
            "ethogram_revision_id": ethogram["id"],
            "format": "bouts_csv",
            "model_id": model["id"],
        },
    )
    assert bouts_csv.status_code == 200, bouts_csv.text
    assert "source_behavior_prediction_id" in bouts_csv.text

    predictions_csv = client.get(
        f"/api/v1/video-tracks/{inference['id']}/behavior-export",
        params={
            "ethogram_revision_id": ethogram["id"],
            "format": "predictions_csv",
            "model_id": model["id"],
        },
    )
    assert predictions_csv.status_code == 200, predictions_csv.text
    assert "score_semantics" in predictions_csv.text


def test_behavior_prediction_review_is_blocked_after_track_revision_changes(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, _video, labeled, inference = _setup(client, monkeypatch)
    ethogram = _ethogram(client, str(project["id"]))
    _label_training_bouts(client, str(labeled["id"]), ethogram)
    model = _train(
        client,
        str(project["id"]),
        str(labeled["id"]),
        ethogram,
    )

    run = client.post(
        f"/api/v1/video-tracks/{inference['id']}/behavior-predictions",
        json={
            "model_id": model["id"],
            "window_frames": 8,
            "stride_frames": 8,
        },
    )
    assert run.status_code == 200, run.text
    prediction = run.json()["predictions"][0]

    updated = client.put(
        f"/api/v1/video-tracks/{inference['id']}",
        json={
            "base_revision": inference["revision"],
            "label_class_id": inference["label_class_id"],
            "keyframes": _keyframes([0, 12, 24, 36, 48, 60, 72, 84]),
            "interpolation": "linear",
            "status": "verified",
        },
    )
    assert updated.status_code == 200, updated.text

    stale = client.get(
        f"/api/v1/video-tracks/{inference['id']}/behavior-predictions"
    )
    assert stale.status_code == 200, stale.text
    assert stale.json()[0]["stale_against_track"] is True

    review = client.put(
        f"/api/v1/behavior-predictions/{prediction['id']}/review",
        json={"action": "accept"},
    )
    assert review.status_code == 400, review.text
    assert "stale" in review.json()["detail"].lower()

    bouts = client.get(
        f"/api/v1/video-tracks/{inference['id']}/behavior-bouts",
        params={"ethogram_revision_id": ethogram["id"]},
    )
    assert bouts.status_code == 200, bouts.text
    assert bouts.json() == []
