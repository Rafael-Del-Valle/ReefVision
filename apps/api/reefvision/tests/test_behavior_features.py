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


def _setup_pose_track(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    project = create_project(client, name)
    monkeypatch.setattr(video_assets_module, "_inspect_video", _fake_metadata)
    video_response = client.post(
        f"/api/v1/projects/{project['id']}/imports/videos",
        files={"file": ("behavior-features.mp4", io.BytesIO(b"video"), "video/mp4")},
    )
    assert video_response.status_code == 201, video_response.text
    video = video_response.json()
    classes = cast(list[dict[str, object]], project["label_classes"])
    track_response = client.post(
        f"/api/v1/videos/{video['id']}/tracks",
        json={
            "label_class_id": str(classes[0]["id"]),
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
                        _observation(
                            "f1-t1",
                            1,
                            82,
                            50,
                            0.91,
                            status="occluded",
                        ),
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
            "interpolation": "linear",
            "status": "verified",
        },
    )
    assert track_response.status_code == 201, track_response.text
    return project, video, track_response.json()


def _features(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    return {item["name"]: item for item in payload["features"]}


def test_behavior_features_combine_track_geometry_and_current_pose_identity(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _project, _video, track = _setup_pose_track(
        client,
        monkeypatch,
        "Behavior features current pose",
    )
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
        f"/api/v1/video-tracks/{track['id']}/behavior-features",
        json={},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schema_version"] == "behavior-feature-vector-0001"
    assert payload["feature_set_version"] == "reefvision-behavior-features-0001"
    assert payload["source_track_revision"] == track["revision"]
    assert payload["pose_identity_status"] == "current"
    assert payload["start_frame"] == 0
    assert payload["end_frame"] == 2
    assert payload["evaluated_seconds_inclusive"] == pytest.approx(0.3)
    assert len(payload["parameters_sha256"]) == 64

    quality = payload["quality"]
    assert quality["evaluated_frame_count"] == 3
    assert quality["track_motion_interval_count"] == 2
    assert quality["pose_sampled_frame_count"] == 3
    assert quality["pose_spatial_sample_count"] == 5
    assert quality["pose_predicted_sample_count"] == 0
    assert quality["pose_resolved_identity_sample_count"] == 5

    features = _features(payload)
    assert features["track.path_length_pixels"]["value"] == pytest.approx(2.0)
    assert features["track.displacement_pixels"]["value"] == pytest.approx(2.0)
    assert features["track.mean_speed_pixels_per_second"]["value"] == pytest.approx(10.0)
    assert features["track.maximum_speed_pixels_per_second"]["value"] == pytest.approx(10.0)
    assert features["track.mean_bbox_area_pixels_squared"]["value"] == pytest.approx(10000.0)
    assert features["track.bbox_area_coefficient_of_variation"]["value"] == pytest.approx(0.0)

    assert features["pose.frame_coverage_fraction"]["value"] == pytest.approx(1.0)
    assert features["pose.mean_landmarks_per_sampled_frame"]["value"] == pytest.approx(5 / 3)
    assert features["pose.predicted_coordinate_fraction"]["value"] == pytest.approx(0.0)
    assert features["pose.mean_spread_pixels"]["value"] == pytest.approx(20.0)
    assert features["pose.mean_pairwise_distance_pixels"]["value"] == pytest.approx(60.0)

    assert features["pose.resolved_identity_fraction"]["available"] is True
    assert features["pose.resolved_identity_fraction"]["value"] == pytest.approx(1.0)
    assert features["pose.identity_path_length_pixels"]["value"] == pytest.approx(8.0)
    assert features["pose.identity_mean_speed_pixels_per_second"]["value"] == pytest.approx(20.0)
    assert features["pose.identity_maximum_speed_pixels_per_second"]["value"] == pytest.approx(20.0)
    assert features["pose.identity_continuity_segment_count"]["value"] == pytest.approx(2.0)


def test_behavior_features_keep_pose_identity_features_missing_until_built(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _project, _video, track = _setup_pose_track(
        client,
        monkeypatch,
        "Behavior features missing identity",
    )

    response = client.post(
        f"/api/v1/video-tracks/{track['id']}/behavior-features",
        json={},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["pose_identity_status"] == "not_built"

    features = _features(payload)
    assert features["pose.mean_spread_pixels"]["available"] is True
    assert features["pose.mean_spread_pixels"]["value"] == pytest.approx(20.0)
    for name in (
        "pose.resolved_identity_fraction",
        "pose.identity_path_length_pixels",
        "pose.identity_mean_speed_pixels_per_second",
        "pose.identity_maximum_speed_pixels_per_second",
        "pose.identity_continuity_segment_count",
    ):
        assert features[name]["available"] is False
        assert features[name]["value"] is None
        assert features[name]["missing_reason"]


def test_behavior_features_mark_identity_motion_unavailable_when_temporal_state_is_stale(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _project, _video, track = _setup_pose_track(
        client,
        monkeypatch,
        "Behavior features stale identity",
    )
    built = client.post(
        f"/api/v1/video-tracks/{track['id']}/pose-temporal-associations",
        json={},
    )
    assert built.status_code == 200, built.text

    updated = client.put(
        f"/api/v1/video-tracks/{track['id']}",
        json={
            "base_revision": track["revision"],
            "label_class_id": track["label_class_id"],
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
                    "bbox": [2, 0, 100, 100],
                    "pose_observations": [
                        _observation("f1-t0", 0, 22, 50, 0.94),
                        _observation("f1-t1", 1, 82, 50, 0.91, status="occluded"),
                    ],
                },
                {
                    "frame": 2,
                    "bbox": [4, 0, 100, 100],
                    "pose_observations": [
                        _observation("f2-t0", 0, 24, 50, 0.92),
                        _observation("f2-t1", 1, 84, 50, 0.90),
                    ],
                },
            ],
            "interpolation": "linear",
            "status": "verified",
        },
    )
    assert updated.status_code == 200, updated.text

    response = client.post(
        f"/api/v1/video-tracks/{track['id']}/behavior-features",
        json={},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["source_track_revision"] == updated.json()["revision"]
    assert payload["pose_identity_status"] == "stale"
    assert payload["pose_identity_warning"]

    features = _features(payload)
    assert features["track.path_length_pixels"]["value"] == pytest.approx(4.0)
    assert features["pose.mean_spread_pixels"]["available"] is True
    assert features["pose.identity_path_length_pixels"]["available"] is False
    assert "older" in features["pose.identity_path_length_pixels"]["missing_reason"].lower()


def test_behavior_features_predicted_coordinates_are_explicit_opt_in(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _project, _video, track = _setup_pose_track(
        client,
        monkeypatch,
        "Behavior features predicted policy",
    )

    excluded = client.post(
        f"/api/v1/video-tracks/{track['id']}/behavior-features",
        json={},
    )
    assert excluded.status_code == 200, excluded.text
    excluded_payload = excluded.json()
    assert excluded_payload["predicted_coordinate_policy"] == "exclude_occluded_predictions"
    assert excluded_payload["quality"]["pose_spatial_sample_count"] == 5

    included = client.post(
        f"/api/v1/video-tracks/{track['id']}/behavior-features",
        json={"include_predicted": True},
    )
    assert included.status_code == 200, included.text
    included_payload = included.json()
    assert included_payload["predicted_coordinate_policy"] == "include_occluded_predictions"
    assert included_payload["quality"]["pose_spatial_sample_count"] == 6
    assert included_payload["quality"]["pose_predicted_sample_count"] == 1
    features = _features(included_payload)
    assert features["pose.predicted_coordinate_fraction"]["value"] == pytest.approx(1 / 6)
