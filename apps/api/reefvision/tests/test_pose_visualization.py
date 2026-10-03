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
        "height_px": 120,
        "frame_count": 20,
        "fps": 10.0,
        "duration_seconds": 2.0,
    }


def _video(
    client: TestClient,
    project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    monkeypatch.setattr(video_assets_module, "_inspect_video", _fake_metadata)
    response = client.post(
        f"/api/v1/projects/{project_id}/imports/videos",
        files={"file": ("jellyfish.mp4", io.BytesIO(b"pose-video"), "video/mp4")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _first_class(project: dict[str, object]) -> str:
    classes = cast(list[dict[str, object]], project["label_classes"])
    return str(classes[0]["id"])


def _observation(
    observation_id: str,
    occurrence: int,
    x: float,
    y: float,
    confidence: float,
    *,
    status: str = "visible",
) -> dict[str, object]:
    return {
        "id": observation_id,
        "semantic_label": "tentacle",
        "occurrence_index": occurrence,
        "x": x,
        "y": y,
        "confidence": confidence,
        "status": status,
        "source": "model",
    }


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
                {
                    "frame": 0,
                    "bbox": [0, 0, 100, 100],
                    "pose_observations": [
                        _observation("f0-t0", 0, 20, 50, 0.95),
                        _observation("f0-t1", 1, 80, 50, 0.93),
                    ],
                },
                {
                    "frame": 1,
                    "bbox": [1, 0, 100, 100],
                    "pose_observations": [
                        _observation("f1-t0", 0, 22, 50, 0.94),
                        _observation("f1-t1", 1, 82, 50, 0.91, status="occluded"),
                    ],
                },
                {
                    "frame": 2,
                    "bbox": [2, 0, 100, 100],
                    "pose_observations": [
                        _observation("f2-t0", 0, 24, 50, 0.92),
                        _observation("f2-t1", 1, 84, 50, 0.90),
                    ],
                },
            ],
            "interpolation": "hold",
            "status": "verified",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_pose_visualization_uses_canonical_points_and_never_invents_paf(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Pose visualization")
    video = _video(client, str(project["id"]), monkeypatch)
    track = _track(client, str(video["id"]), _first_class(project))

    before_temporal = client.post(
        f"/api/v1/video-tracks/{track['id']}/pose-visualization",
        json={"grid_rows": 2, "grid_columns": 2},
    )
    assert before_temporal.status_code == 200, before_temporal.text
    raw = before_temporal.json()
    assert raw["schema_version"] == "pose-visualization-0001"
    assert raw["coordinate_space"] == "source_pixels"
    assert raw["sampling_policy"] == "persisted_canonical_pose_keyframes"
    assert raw["identity_status"] == "not_built"
    assert raw["spatial_sample_count"] == 5
    assert raw["observed_sample_count"] == 5
    assert raw["predicted_sample_count"] == 0
    assert raw["trajectories"] == []
    assert raw["paf"]["available"] is False
    assert raw["paf"]["persistence_state"] == "not_persisted"

    built = client.post(
        f"/api/v1/video-tracks/{track['id']}/pose-temporal-associations",
        json={
            "max_gap_frames": 2,
            "max_normalized_displacement": 0.35,
            "ambiguity_margin": 0.02,
            "confirm_after_observations": 3,
        },
    )
    assert built.status_code == 200, built.text

    response = client.post(
        f"/api/v1/video-tracks/{track['id']}/pose-visualization",
        json={
            "grid_rows": 2,
            "grid_columns": 2,
            "include_predicted": True,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["identity_status"] == "current"
    assert payload["spatial_sample_count"] == 6
    assert payload["observed_sample_count"] == 5
    assert payload["predicted_sample_count"] == 1
    assert payload["resolved_identity_sample_count"] == 6
    assert payload["unresolved_identity_sample_count"] == 0
    assert len(payload["trajectories"]) == 2
    assert sum(item["sample_count"] for item in payload["cells"]) == 6
    assert sum(item["movement_segment_count"] for item in payload["cells"]) == 4
    assert sum(item["movement_distance_pixels"] for item in payload["cells"]) == pytest.approx(
        8.0
    )
    assert payload["activity_segment_count"] == 4

    all_points = [
        point
        for trajectory in payload["trajectories"]
        for point in trajectory["points"]
    ]
    predicted = [point for point in all_points if point["coordinate_kind"] == "predicted"]
    assert len(predicted) == 1
    assert predicted[0]["visibility_state"] == "occluded"


def test_pose_visualization_filters_uncertain_and_low_confidence_without_zeroing_unknowns(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Pose visualization filtering")
    video = _video(client, str(project["id"]), monkeypatch)
    response = client.post(
        f"/api/v1/videos/{video['id']}/tracks",
        json={
            "label_class_id": _first_class(project),
            "keyframes": [
                {
                    "frame": 0,
                    "bbox": [0, 0, 100, 100],
                    "pose_observations": [
                        {
                            "id": "visible-high",
                            "semantic_label": "bell",
                            "occurrence_index": 0,
                            "x": 20,
                            "y": 20,
                            "confidence": 0.9,
                            "status": "visible",
                            "source": "model",
                        },
                        {
                            "id": "uncertain-high",
                            "semantic_label": "tentacle",
                            "occurrence_index": 0,
                            "x": 30,
                            "y": 30,
                            "confidence": 0.8,
                            "status": "uncertain",
                            "source": "model",
                        },
                        {
                            "id": "visible-low",
                            "semantic_label": "tentacle",
                            "occurrence_index": 1,
                            "x": 40,
                            "y": 40,
                            "confidence": 0.2,
                            "status": "visible",
                            "source": "model",
                        },
                    ],
                }
            ],
            "status": "verified",
        },
    )
    assert response.status_code == 201, response.text
    track = response.json()

    visualization = client.post(
        f"/api/v1/video-tracks/{track['id']}/pose-visualization",
        json={
            "grid_rows": 4,
            "grid_columns": 4,
            "include_uncertain": False,
            "minimum_landmark_confidence": 0.5,
        },
    )
    assert visualization.status_code == 200, visualization.text
    payload = visualization.json()
    assert payload["spatial_sample_count"] == 1
    assert payload["observed_sample_count"] == 1
    assert payload["excluded_filter_count"] == 2
    assert payload["cells"][0]["sample_fraction"] in {0.0, 1.0}
