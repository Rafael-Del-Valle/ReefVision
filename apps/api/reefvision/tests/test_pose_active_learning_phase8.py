from __future__ import annotations

import copy
import io
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from reefvision.db.models import (
    ModelRegistration,
    PoseActiveLearningCandidate,
    PoseLandmarkCorrection,
    VideoTrack,
)
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


def _register_pose_model(
    client: TestClient,
    project_id: str,
    *,
    name: str,
    provider_name: str,
    sha_character: str,
) -> str:
    app = cast(FastAPI, client.app)

    with app.state.session_factory() as session:
        model = ModelRegistration(
            project_id=project_id,
            purpose="detector",
            display_name=name,
            source_filename=f"{name}.bin",
            managed_path=f"models/{name}.bin",
            sha256=sha_character * 64,
            file_size_bytes=1,
            framework=provider_name,
            task="pose",
            provider_name=provider_name,
            provider_version="test",
            class_map_json={},
            metadata_json={},
        )
        session.add(model)
        session.commit()
        session.refresh(model)
        return model.id


def _attach_pose_model(
    client: TestClient,
    track_id: str,
    *,
    model_id: str,
    provider_name: str,
    x_offset: float = 0.0,
    heatmap_entropy: float | None = None,
    paf_ambiguity: float | None = None,
) -> int:
    app = cast(FastAPI, client.app)

    with app.state.session_factory() as session:
        track = session.get(VideoTrack, track_id)
        assert track is not None

        keyframes = copy.deepcopy(track.keyframes_json)

        for frame in keyframes:
            bbox = frame.get("bbox")
            if isinstance(bbox, list) and len(bbox) == 4:
                bbox[0] = float(bbox[0]) + x_offset

            observations = frame.get("pose_observations")
            if isinstance(observations, list):
                for observation in observations:
                    if isinstance(observation, dict):
                        observation["x"] = float(observation["x"]) + x_offset

            frame["pose_uncertainty"] = {
                "schema_version": "pose-provider-uncertainty-0001",
                "provider_id": provider_name,
                "provider_version": "test",
                "capabilities": {
                    "keypoint_confidence": True,
                    "heatmap_entropy": heatmap_entropy is not None,
                    "paf_ambiguity": paf_ambiguity is not None,
                },
                "available_signals": [
                    "keypoint_confidence",
                    *(["heatmap_entropy"] if heatmap_entropy is not None else []),
                    *(["paf_ambiguity"] if paf_ambiguity is not None else []),
                ],
                "mean_keypoint_confidence": 0.75,
                "minimum_keypoint_confidence": 0.25,
                "heatmap_entropy": heatmap_entropy,
                "paf_ambiguity": paf_ambiguity,
            }

        track.source_model_id = model_id
        track.metadata_json = {
            **dict(track.metadata_json or {}),
            "provider_name": provider_name,
            "provider_version": "test",
            "pose_tracking": True,
        }
        track.keyframes_json = keyframes
        track.revision += 1

        revision = track.revision
        session.commit()
        return revision


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

    # The correction must exist before the candidate can reference it with
    # SQLite foreign-key enforcement enabled; a verified result is auditable.
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        assert session.scalar(text("PRAGMA foreign_keys")) == 1
        persisted = session.get(PoseActiveLearningCandidate, str(candidate["id"]))
        correction = session.get(PoseLandmarkCorrection, verified_payload["correction_id"])
        assert persisted is not None
        assert correction is not None
        assert persisted.correction_id == correction.id
        assert correction.parent_video_track_id == track["id"]
        assert session.scalar(text("PRAGMA foreign_key_check")) is None

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


def test_pose_active_learning_uses_provider_native_uncertainty_only_when_available(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(
        client,
        "Pose provider uncertainty",
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
    model_id = _register_pose_model(
        client,
        str(project["id"]),
        name="provider-native-pose",
        provider_name="future_pose_provider",
        sha_character="a",
    )

    _attach_pose_model(
        client,
        str(track["id"]),
        model_id=model_id,
        provider_name="future_pose_provider",
        heatmap_entropy=0.74,
        paf_ambiguity=0.46,
    )
    _build_temporal(client, str(track["id"]))

    created = client.post(
        f"/api/v1/projects/{project['id']}/pose-active-learning-rounds",
        json={
            "name": "Provider uncertainty round",
            "video_id": video["id"],
            "track_ids": [track["id"]],
            "model_ids": [model_id],
            "requested_size": 1,
            "minimum_frame_spacing": 0,
        },
    )
    assert created.status_code == 201, created.text

    candidate = client.get(
        f"/api/v1/pose-active-learning-rounds/{created.json()['id']}/candidates"
    ).json()[0]

    assert candidate["score_components_json"]["heatmap_entropy"] == pytest.approx(0.74)
    assert candidate["score_components_json"]["paf_ambiguity"] == pytest.approx(0.46)

    evidence = candidate["provenance_json"]["provider_uncertainty_evidence"]
    assert evidence["available"] is True
    assert evidence["provider_id"] == "future_pose_provider"
    assert evidence["capabilities"]["heatmap_entropy"] is True
    assert evidence["capabilities"]["paf_ambiguity"] is True


def test_pose_active_learning_does_not_fabricate_heatmap_or_paf_scores(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(
        client,
        "Pose unsupported uncertainty",
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
    model_id = _register_pose_model(
        client,
        str(project["id"]),
        name="ultralytics-pose-no-heatmap",
        provider_name="ultralytics",
        sha_character="b",
    )

    _attach_pose_model(
        client,
        str(track["id"]),
        model_id=model_id,
        provider_name="ultralytics",
    )
    _build_temporal(client, str(track["id"]))

    created = client.post(
        f"/api/v1/projects/{project['id']}/pose-active-learning-rounds",
        json={
            "name": "No fabricated provider uncertainty",
            "video_id": video["id"],
            "track_ids": [track["id"]],
            "model_ids": [model_id],
            "requested_size": 1,
            "minimum_frame_spacing": 0,
        },
    )
    assert created.status_code == 201, created.text

    candidate = client.get(
        f"/api/v1/pose-active-learning-rounds/{created.json()['id']}/candidates"
    ).json()[0]

    components = candidate["score_components_json"]

    assert "heatmap_entropy" not in components
    assert "paf_ambiguity" not in components

    evidence = candidate["provenance_json"]["provider_uncertainty_evidence"]
    assert evidence["available"] is True
    assert evidence["capabilities"]["heatmap_entropy"] is False
    assert evidence["capabilities"]["paf_ambiguity"] is False


def test_pose_active_learning_scores_cross_model_repeated_landmark_disagreement(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(
        client,
        "Cross-model pose disagreement",
    )
    video = _video(
        client,
        str(project["id"]),
        monkeypatch,
    )
    label_class_id = _first_class(project)

    first_track = _track(
        client,
        str(video["id"]),
        label_class_id,
    )
    second_track = _track(
        client,
        str(video["id"]),
        label_class_id,
    )

    first_model = _register_pose_model(
        client,
        str(project["id"]),
        name="pose-model-a",
        provider_name="ultralytics",
        sha_character="c",
    )
    second_model = _register_pose_model(
        client,
        str(project["id"]),
        name="pose-model-b",
        provider_name="sleap_nn",
        sha_character="d",
    )

    _attach_pose_model(
        client,
        str(first_track["id"]),
        model_id=first_model,
        provider_name="ultralytics",
        x_offset=0.0,
    )
    _attach_pose_model(
        client,
        str(second_track["id"]),
        model_id=second_model,
        provider_name="sleap_nn",
        x_offset=16.0,
    )

    _build_temporal(client, str(first_track["id"]))
    _build_temporal(client, str(second_track["id"]))

    created = client.post(
        f"/api/v1/projects/{project['id']}/pose-active-learning-rounds",
        json={
            "name": "Cross-model disagreement review",
            "video_id": video["id"],
            "track_ids": [first_track["id"]],
            "model_ids": [
                first_model,
                second_model,
            ],
            "requested_size": 1,
            "minimum_frame_spacing": 0,
        },
    )
    assert created.status_code == 201, created.text

    candidate = client.get(
        f"/api/v1/pose-active-learning-rounds/{created.json()['id']}/candidates"
    ).json()[0]

    disagreement = candidate["score_components_json"].get("model_disagreement")

    assert disagreement is not None
    assert disagreement > 0

    evidence = candidate["provenance_json"]["model_disagreement_evidence"]
    assert evidence["available"] is True
    assert evidence["comparison_count"] == 1
    assert evidence["comparisons"][0]["model_id"] == second_model
    assert evidence["comparisons"][0]["video_track_id"] == second_track["id"]
    assert evidence["comparisons"][0]["bbox_iou"] > 0.10
    assert evidence["method"] == "repeated-label-order-invariant-symmetric-nearest-distance"


def test_pose_active_learning_diversity_selection_is_deterministic(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(
        client,
        "Pose diversity selection",
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

    payload = {
        "name": "Uncertainty plus diversity",
        "video_id": video["id"],
        "track_ids": [track["id"]],
        "selection_unit": "frame",
        "selection_mode": "uncertainty_diverse",
        "diversity_weight": 0.35,
        "requested_size": 2,
        "minimum_frame_spacing": 0,
    }

    first = client.post(
        f"/api/v1/projects/{project['id']}/pose-active-learning-rounds",
        json=payload,
    )
    assert first.status_code == 201, first.text

    first_payload = first.json()
    manifest = first_payload["selection_manifest_json"]

    assert manifest["selection_mode"] == ("uncertainty_diverse")
    assert manifest["diversity_weight"] == pytest.approx(0.35)

    assert len(manifest["items"]) == 2

    for item in manifest["items"]:
        assert 0 <= item["selection_score"] <= 1
        assert 0 <= item["diversity_score"] <= 1

    config = first_payload["scoring_config_json"]

    assert config["algorithm_version"] == "0003"
    assert config["selection_mode"] == ("uncertainty_diverse")
    assert config["diversity_weight"] == pytest.approx(0.35)

    second = client.post(
        f"/api/v1/projects/{project['id']}/pose-active-learning-rounds",
        json=payload,
    )
    assert second.status_code == 201, second.text

    second_payload = second.json()

    assert second_payload["id"] == first_payload["id"]
    assert second_payload["selection_sha256"] == first_payload["selection_sha256"]
