from __future__ import annotations

import io
from typing import cast

import pytest
from fastapi.testclient import TestClient

from reefvision.db.models import PoseIdentityObservation, VideoTrack
from reefvision.jobs.pose_identity_tracking import process_pose_identity_tracking_job
from reefvision.services import video_assets as video_assets_module
from reefvision.tests.test_annotations import create_project

SCHEMA_ID = "reefpose-test-fish"
SCHEMA_HASH = "a" * 64


def _fake_metadata(_path: object) -> dict[str, float | int]:
    return {
        "width_px": 320,
        "height_px": 180,
        "frame_count": 12,
        "fps": 10.0,
        "duration_seconds": 1.2,
    }


def _video(
    client: TestClient, project_id: str, monkeypatch: pytest.MonkeyPatch, name: str
) -> dict[str, object]:
    monkeypatch.setattr(video_assets_module, "_inspect_video", _fake_metadata)
    response = client.post(
        f"/api/v1/projects/{project_id}/imports/videos",
        files={"file": (f"{name}.mp4", io.BytesIO(name.encode()), "video/mp4")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _first_class(project: dict[str, object]) -> str:
    return str(cast(list[dict[str, object]], project["label_classes"])[0]["id"])


def _track(
    client: TestClient,
    video_id: str,
    label_class_id: str,
    *,
    offset: float,
    prefix: str,
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/videos/{video_id}/tracks",
        json={
            "label_class_id": label_class_id,
            "geometry_kind": "bbox",
            "keyframes": [
                {
                    "frame": frame,
                    "bbox": [offset + frame * 4, 20, 30, 15],
                    "confidence": 0.9,
                    "pose_observations": [
                        {
                            "id": f"{prefix}-{frame}-nose",
                            "landmark_id": "nose",
                            "semantic_label": "nose",
                            "occurrence_index": 0,
                            "x": offset + frame * 4 + 5,
                            "y": 25,
                            "confidence": 0.9,
                            "status": "visible",
                            "source": "model",
                        }
                    ],
                }
                for frame in (0, 1, 2)
            ],
            "interpolation": "hold",
            "status": "verified",
        },
    )
    assert response.status_code == 201, response.text
    track = response.json()
    with client.app.state.session_factory() as session:
        record = session.get(VideoTrack, str(track["id"]))
        assert record is not None
        record.metadata_json = {
            **dict(record.metadata_json or {}),
            "pose_landmark_schema": {
                "schema_id": SCHEMA_ID,
                "schema_revision": 1,
                "content_hash": SCHEMA_HASH,
            },
        }
        session.commit()
    return track


def _submit(
    client: TestClient, project_id: str, video_id: str, track_ids: list[str]
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/projects/{project_id}/pose-identity-runs",
        json={
            "video_id": video_id,
            "source_track_ids": track_ids,
            "pose_schema_id": SCHEMA_ID,
            "pose_schema_revision": 1,
            "pose_schema_content_hash": SCHEMA_HASH,
            "parameters": {
                "max_gap_frames": 2,
                "max_normalized_distance": 4.0,
                "acceptance_threshold": 2.0,
            },
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def test_api_runs_association_persists_corrections_and_exports_provenance(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = create_project(client, "Pose identity API")
    video = _video(client, str(project["id"]), monkeypatch, "identity")
    label_id = _first_class(project)
    tracks = [
        _track(client, str(video["id"]), label_id, offset=10, prefix="left"),
        _track(client, str(video["id"]), label_id, offset=150, prefix="right"),
    ]
    job = _submit(
        client,
        str(project["id"]),
        str(video["id"]),
        [str(item["id"]) for item in tracks],
    )
    run_id = str(cast(dict[str, object], job["result_json"])["run_id"])

    assert process_pose_identity_tracking_job(
        client.app.state.settings, client.app.state.session_factory, str(job["id"])
    )

    loaded = client.get(f"/api/v1/pose-identity-runs/{run_id}")
    assert loaded.status_code == 200, loaded.text
    assert loaded.json()["status"] == "completed"
    assert loaded.json()["source_coordinate_space"] == "source_pixels"

    identities = client.get(f"/api/v1/pose-identity-runs/{run_id}/identities").json()
    observations = client.get(f"/api/v1/pose-identity-runs/{run_id}/observations").json()
    decisions = client.get(f"/api/v1/pose-identity-runs/{run_id}/decisions").json()
    assert len(identities) == 2
    assert len(observations) == 6
    assert any(item["selected"] for item in decisions)
    assert all("motion_cost" in item["score_components_json"] for item in decisions)

    target = observations[0]
    destination = next(item for item in identities if item["id"] != target["animal_identity_id"])
    corrected = client.post(
        f"/api/v1/pose-identity-runs/{run_id}/corrections",
        json={
            "action": "reassign",
            "target_type": "observation",
            "target_id": target["id"],
            "destination_identity_id": destination["id"],
            "reason": "Synthetic crossing correction",
            "actor": "scientist@example.test",
        },
    )
    assert corrected.status_code == 400, corrected.text
    assert "already has an observation" in corrected.json()["detail"]

    corrected = client.post(
        f"/api/v1/pose-identity-runs/{run_id}/corrections",
        json={
            "action": "swap",
            "target_type": "identity",
            "target_id": target["animal_identity_id"],
            "destination_identity_id": destination["id"],
            "frame_start": target["frame_index"],
            "frame_end": target["frame_index"],
            "reason": "Synthetic crossing correction",
            "actor": "scientist@example.test",
        },
    )
    assert corrected.status_code == 201, corrected.text
    assert corrected.json()["before_sha256"] != corrected.json()["after_sha256"]

    history = client.get(f"/api/v1/pose-identity-runs/{run_id}/corrections").json()
    current = client.get(f"/api/v1/pose-identity-runs/{run_id}/observations").json()
    revisions = client.get(
        f"/api/v1/pose-identity-runs/{run_id}/observations?include_history=true"
    ).json()
    assert [item["revision"] for item in history] == [2]
    assert len(current) == 6
    assert len(revisions) == 8
    assert any(
        item["supersedes_observation_id"] == target["id"]
        and item["animal_identity_id"] == destination["id"]
        for item in revisions
    )

    exported = client.get(f"/api/v1/pose-identity-runs/{run_id}/export?format=json")
    assert exported.status_code == 200, exported.text
    payload = exported.json()
    assert payload["association_run"]["parameters_sha256"]
    assert payload["association_run"]["input_manifest_sha256"]
    assert payload["corrections"][0]["actor"] == "scientist@example.test"
    assert payload["coordinate_space"] == "source_pixels"


def test_review_queue_drops_resolved_low_confidence_observations(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = create_project(client, "Pose identity review queue")
    video = _video(client, str(project["id"]), monkeypatch, "review-queue")
    track = _track(
        client,
        str(video["id"]),
        _first_class(project),
        offset=10,
        prefix="review",
    )
    job = _submit(client, str(project["id"]), str(video["id"]), [str(track["id"])])
    run_id = str(cast(dict[str, object], job["result_json"])["run_id"])
    assert process_pose_identity_tracking_job(
        client.app.state.settings, client.app.state.session_factory, str(job["id"])
    )

    observations = client.get(f"/api/v1/pose-identity-runs/{run_id}/observations").json()
    target = observations[0]
    with client.app.state.session_factory() as session:
        record = session.get(PoseIdentityObservation, target["id"])
        assert record is not None
        record.association_confidence = 0.01
        session.commit()

    queued = client.get(f"/api/v1/pose-identity-runs/{run_id}/review-queue").json()
    assert target["id"] in {item["id"] for item in queued}
    resolved = client.post(
        f"/api/v1/pose-identity-runs/{run_id}/corrections",
        json={
            "action": "reject",
            "target_type": "observation",
            "target_id": target["id"],
            "actor": "queue-reviewer",
        },
    )
    assert resolved.status_code == 201, resolved.text
    remaining = client.get(f"/api/v1/pose-identity-runs/{run_id}/review-queue").json()
    assert all(
        item["observation_series_id"] != target["observation_series_id"] for item in remaining
    )


def test_submission_rejects_foreign_video_and_schema_mismatch(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = create_project(client, "Pose identity validation")
    first_video = _video(client, str(project["id"]), monkeypatch, "first")
    second_video = _video(client, str(project["id"]), monkeypatch, "second")
    track = _track(
        client,
        str(first_video["id"]),
        _first_class(project),
        offset=10,
        prefix="fish",
    )

    foreign = client.post(
        f"/api/v1/projects/{project['id']}/pose-identity-runs",
        json={
            "video_id": second_video["id"],
            "source_track_ids": [track["id"]],
            "pose_schema_id": SCHEMA_ID,
            "pose_schema_revision": 1,
            "pose_schema_content_hash": SCHEMA_HASH,
        },
    )
    assert foreign.status_code == 400
    assert "selected video" in foreign.json()["detail"]

    mismatch = client.post(
        f"/api/v1/projects/{project['id']}/pose-identity-runs",
        json={
            "video_id": first_video["id"],
            "source_track_ids": [track["id"]],
            "pose_schema_id": SCHEMA_ID,
            "pose_schema_revision": 2,
            "pose_schema_content_hash": "b" * 64,
        },
    )
    assert mismatch.status_code == 400
    assert "schema" in mismatch.json()["detail"].lower()


def test_swap_split_and_merge_create_reversible_observation_revisions(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = create_project(client, "Pose identity structural corrections")
    video = _video(client, str(project["id"]), monkeypatch, "structural")
    label_id = _first_class(project)
    tracks = [
        _track(client, str(video["id"]), label_id, offset=10, prefix="one"),
        _track(client, str(video["id"]), label_id, offset=150, prefix="two"),
    ]
    job = _submit(
        client,
        str(project["id"]),
        str(video["id"]),
        [str(item["id"]) for item in tracks],
    )
    run_id = str(job["result_json"]["run_id"])
    assert process_pose_identity_tracking_job(
        client.app.state.settings, client.app.state.session_factory, str(job["id"])
    )
    identities = client.get(f"/api/v1/pose-identity-runs/{run_id}/identities").json()
    first, second = identities

    swap = client.post(
        f"/api/v1/pose-identity-runs/{run_id}/corrections",
        json={
            "action": "swap",
            "target_type": "identity",
            "target_id": first["id"],
            "destination_identity_id": second["id"],
            "frame_start": 1,
            "frame_end": 1,
        },
    )
    assert swap.status_code == 201, swap.text
    swap_changes = swap.json()["after_json"]["changes"]
    assert len(swap_changes) == 2
    assert {item["identity_id"] for item in swap_changes} == {first["id"], second["id"]}

    split = client.post(
        f"/api/v1/pose-identity-runs/{run_id}/corrections",
        json={
            "action": "split",
            "target_type": "identity",
            "target_id": first["id"],
            "frame_start": 2,
            "frame_end": 2,
        },
    )
    assert split.status_code == 201, split.text
    split_identity_id = split.json()["after_json"]["changes"][0]["identity_id"]
    assert split_identity_id not in {first["id"], second["id"]}

    merge = client.post(
        f"/api/v1/pose-identity-runs/{run_id}/corrections",
        json={
            "action": "merge",
            "target_type": "identity",
            "target_id": split_identity_id,
            "destination_identity_id": first["id"],
        },
    )
    assert merge.status_code == 201, merge.text
    history = client.get(f"/api/v1/pose-identity-runs/{run_id}/corrections").json()
    assert [item["action"] for item in history] == ["swap", "split", "merge"]
    assert [item["revision"] for item in history] == [2, 3, 4]
