from __future__ import annotations

import io
from typing import cast

import pytest
from fastapi.testclient import TestClient

from reefvision.services import video_assets as video_assets_module
from reefvision.tests.test_annotations import create_project


def _fake_metadata(_path: object) -> dict[str, float | int]:
    return {
        "width_px": 320,
        "height_px": 240,
        "frame_count": 30,
        "fps": 10.0,
        "duration_seconds": 3.0,
    }


def _video(
    client: TestClient,
    project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    monkeypatch.setattr(
        video_assets_module,
        "_inspect_video",
        _fake_metadata,
    )
    response = client.post(
        f"/api/v1/projects/{project_id}/imports/videos",
        files={
            "file": (
                "pose-al-jellyfish.mp4",
                io.BytesIO(b"pose-active-learning-video"),
                "video/mp4",
            )
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _first_class(project: dict[str, object]) -> str:
    classes = cast(
        list[dict[str, object]],
        project["label_classes"],
    )
    return str(classes[0]["id"])


def _pose(
    observation_id: str,
    occurrence_index: int,
    x: float,
    y: float,
    confidence: float,
    *,
    status: str = "visible",
) -> dict[str, object]:
    return {
        "id": observation_id,
        "semantic_label": "tentacle",
        "occurrence_index": occurrence_index,
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
                    "bbox": [10, 10, 120, 100],
                    "pose_observations": [
                        _pose("f0-t0", 0, 40, 70, 0.95),
                        _pose("f0-t1", 1, 90, 70, 0.93),
                    ],
                },
                {
                    "frame": 1,
                    "bbox": [12, 10, 120, 100],
                    "pose_observations": [
                        _pose("f1-t0", 0, 44, 70, 0.91),
                        _pose(
                            "f1-t1",
                            1,
                            94,
                            70,
                            0.28,
                            status="uncertain",
                        ),
                    ],
                },
                {
                    "frame": 5,
                    "bbox": [20, 10, 120, 100],
                    "pose_observations": [
                        _pose("f5-t0", 0, 55, 70, 0.88),
                        _pose("f5-t1", 1, 104, 70, 0.32),
                    ],
                },
            ],
            "interpolation": "hold",
            "status": "verified",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _build_temporal(
    client: TestClient,
    track_id: str,
) -> None:
    response = client.post(
        f"/api/v1/video-tracks/{track_id}/pose-temporal-associations",
        json={
            "max_gap_frames": 1,
            "max_normalized_displacement": 0.35,
            "ambiguity_margin": 0.10,
            "confirm_after_observations": 2,
        },
    )
    assert response.status_code == 200, response.text


def test_pose_active_learning_selects_explainable_clip_and_editor_handoff(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(
        client,
        "Pose Active Learning selection",
    )
    video = _video(
        client,
        str(project["id"]),
        monkeypatch,
    )
    track = _track(
        client,
        str(video["id"]),
        _first_class(project),
    )
    _build_temporal(client, str(track["id"]))

    created = client.post(
        f"/api/v1/projects/{project['id']}/pose-active-learning-rounds",
        json={
            "name": "Tentacle uncertainty review",
            "video_id": video["id"],
            "track_ids": [track["id"]],
            "selection_unit": "clip",
            "requested_size": 1,
            "clip_radius_frames": 2,
            "minimum_frame_spacing": 0,
        },
    )
    assert created.status_code == 201, created.text
    round_payload = created.json()
    assert round_payload["selected_count"] == 1
    assert round_payload["selection_unit"] == "clip"
    assert len(round_payload["selection_sha256"]) == 64

    candidates_response = client.get(
        f"/api/v1/pose-active-learning-rounds/{round_payload['id']}/candidates"
    )
    assert candidates_response.status_code == 200
    candidates = candidates_response.json()
    assert len(candidates) == 1

    candidate = candidates[0]
    assert 0 <= candidate["acquisition_score"] <= 1
    assert candidate["score_components_json"]["low_landmark_confidence"] > 0
    assert candidate["score_components_json"]["repeated_landmark_ambiguity"] >= 0
    assert candidate["score_components_json"]["identity_break_signal"] > 0
    assert candidate["reason_codes_json"]
    assert len(candidate["provenance_sha256"]) == 64
    assert candidate["review_target"]["workspace"] == "pose_annotation_editor"
    assert candidate["review_target"]["video_track_id"] == track["id"]
    assert candidate["frame_start"] <= candidate["focus_frame"] <= candidate["frame_end"]


def test_pose_active_learning_editor_review_creates_verified_canonical_provenance(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(
        client,
        "Pose Active Learning review",
    )
    video = _video(
        client,
        str(project["id"]),
        monkeypatch,
    )
    track = _track(
        client,
        str(video["id"]),
        _first_class(project),
    )
    _build_temporal(client, str(track["id"]))

    round_response = client.post(
        f"/api/v1/projects/{project['id']}/pose-active-learning-rounds",
        json={
            "name": "Scientist pose review",
            "video_id": video["id"],
            "track_ids": [track["id"]],
            "selection_unit": "frame",
            "requested_size": 1,
            "minimum_frame_spacing": 0,
        },
    )
    assert round_response.status_code == 201
    round_payload = round_response.json()

    candidate = client.get(
        f"/api/v1/pose-active-learning-rounds/{round_payload['id']}/candidates"
    ).json()[0]

    started = client.put(
        f"/api/v1/pose-active-learning-candidates/{candidate['id']}/review",
        json={
            "action": "start_review",
            "reviewed_by": "scientist",
        },
    )
    assert started.status_code == 200, started.text
    assert started.json()["review_status"] == "in_review"

    tracks = client.get(f"/api/v1/videos/{video['id']}/tracks").json()
    current = next(item for item in tracks if item["id"] == track["id"])

    focus_frame = candidate["focus_frame"]
    keyframes = current["keyframes_json"]

    for frame in keyframes:
        if frame["frame"] != focus_frame:
            continue
        observations = frame.get("pose_observations", [])
        if observations:
            observations[0]["x"] = float(observations[0]["x"]) + 1.0
            observations[0]["source"] = "corrected"

    updated = client.put(
        f"/api/v1/video-tracks/{track['id']}",
        json={
            "base_revision": current["revision"],
            "label_class_id": current["label_class_id"],
            "keyframes": keyframes,
            "interpolation": current["interpolation"],
            "status": current["status"],
        },
    )
    assert updated.status_code == 200, updated.text
    updated_track = updated.json()

    verified = client.put(
        f"/api/v1/pose-active-learning-candidates/{candidate['id']}/review",
        json={
            "action": "verify",
            "reviewed_by": "scientist",
            "verified_track_revision": (updated_track["revision"]),
            "note": "Corrected tentacle placement in Pose Annotation Editor.",
        },
    )
    assert verified.status_code == 200, verified.text
    verified_payload = verified.json()
    assert verified_payload["review_status"] == "verified"
    assert verified_payload["verified_track_revision"] == updated_track["revision"]
    assert len(verified_payload["verified_pose_sha256"]) == 64
    assert verified_payload["correction_id"] is not None

    summary = client.get(f"/api/v1/video-tracks/{track['id']}/pose-temporal")
    assert summary.status_code == 200
    assert any(
        correction["action"] == "verify_active_learning_pose"
        for correction in summary.json()["corrections"]
    )

    manifest = client.get(
        f"/api/v1/pose-active-learning-rounds/{round_payload['id']}/retraining-manifest"
    )
    assert manifest.status_code == 200
    payload = manifest.json()
    assert payload["retraining_ready"] is True
    assert payload["verified_candidate_count"] == 1
    assert payload["pending_candidate_count"] == 0
    assert (
        payload["candidates"][0]["verified_pose_sha256"] == verified_payload["verified_pose_sha256"]
    )


def test_pose_active_learning_blocks_stale_candidate_before_review(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(
        client,
        "Pose Active Learning stale guard",
    )
    video = _video(
        client,
        str(project["id"]),
        monkeypatch,
    )
    track = _track(
        client,
        str(video["id"]),
        _first_class(project),
    )
    _build_temporal(client, str(track["id"]))

    round_payload = client.post(
        f"/api/v1/projects/{project['id']}/pose-active-learning-rounds",
        json={
            "name": "Stale candidate test",
            "video_id": video["id"],
            "track_ids": [track["id"]],
            "requested_size": 1,
            "minimum_frame_spacing": 0,
        },
    ).json()

    candidate = client.get(
        f"/api/v1/pose-active-learning-rounds/{round_payload['id']}/candidates"
    ).json()[0]

    current = client.get(f"/api/v1/videos/{video['id']}/tracks").json()[0]

    changed = client.put(
        f"/api/v1/video-tracks/{track['id']}",
        json={
            "base_revision": current["revision"],
            "label_class_id": current["label_class_id"],
            "keyframes": current["keyframes_json"],
            "interpolation": current["interpolation"],
            "status": "draft",
        },
    )
    assert changed.status_code == 200

    stale = client.put(
        f"/api/v1/pose-active-learning-candidates/{candidate['id']}/review",
        json={
            "action": "start_review",
            "reviewed_by": "scientist",
        },
    )
    assert stale.status_code == 409
    assert "stale" in stale.json()["detail"].lower()
