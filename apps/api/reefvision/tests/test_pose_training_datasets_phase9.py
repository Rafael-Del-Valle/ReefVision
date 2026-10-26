from __future__ import annotations

import copy
import hashlib
import io
import json
import zipfile
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import (
    PoseActiveLearningCandidate,
    PoseLandmarkObservation,
    PoseLandmarkSchema,
    PoseLandmarkSchemaRevision,
    PoseLandmarkTrack,
    PoseTrainingDataset,
    PoseTrainingDatasetItem,
    VideoTrack,
)
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_pose_active_learning_phase8 import (
    _build_temporal,
    _first_class,
    _track,
    _video,
)


def _persist_test_pose_schema(
    client: TestClient,
    *,
    project_id: str,
    track_id: str,
) -> None:
    """Promote synthetic temporal pose rows onto an immutable schema."""

    app = cast(
        FastAPI,
        client.app,
    )

    groups = [
        {
            "name": "tentacle",
            "count": 2,
        }
    ]

    expanded_labels = [
        "tentacle",
        "tentacle",
    ]

    payload = {
        "schema_version": "pose-landmarks-0001",
        "groups": groups,
        "expanded_labels": expanded_labels,
        "keypoint_count": 2,
        "allows_repeated_labels": True,
    }

    content_hash = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    with app.state.session_factory() as session:
        schema = PoseLandmarkSchema(
            project_id=project_id,
            name="Phase 9 repeated tentacle schema",
        )

        session.add(schema)
        session.flush()

        revision = PoseLandmarkSchemaRevision(
            schema_id=schema.id,
            revision=1,
            schema_version="pose-landmarks-0001",
            groups_json=groups,
            expanded_labels_json=expanded_labels,
            keypoint_count=2,
            allows_repeated_labels=True,
            content_hash=content_hash,
        )

        session.add(revision)
        session.flush()

        observations = list(
            session.query(PoseLandmarkObservation).filter_by(parent_video_track_id=track_id)
        )

        landmark_tracks = list(
            session.query(PoseLandmarkTrack).filter_by(parent_video_track_id=track_id)
        )

        assert observations
        assert landmark_tracks

        for observation in observations:
            observation.pose_schema_id = schema.id
            observation.pose_schema_revision = 1

        for landmark_track in landmark_tracks:
            landmark_track.pose_schema_id = schema.id
            landmark_track.pose_schema_revision = 1

        session.commit()


def _verified_round(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    persist_schema: bool = True,
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    project = create_project(
        client,
        "Phase 9 verified pose dataset",
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
    _build_temporal(
        client,
        str(track["id"]),
    )

    if persist_schema:
        _persist_test_pose_schema(
            client,
            project_id=str(project["id"]),
            track_id=str(track["id"]),
        )

    created = client.post(
        f"/api/v1/projects/{project['id']}/pose-active-learning-rounds",
        json={
            "name": "Scientist verified tentacles",
            "video_id": video["id"],
            "track_ids": [track["id"]],
            "selection_unit": "frame",
            "requested_size": 1,
            "minimum_frame_spacing": 0,
        },
    )
    assert created.status_code == 201, created.text

    round_payload = created.json()

    candidate = client.get(
        f"/api/v1/pose-active-learning-rounds/{round_payload['id']}/candidates"
    ).json()[0]

    verified = client.put(
        f"/api/v1/pose-active-learning-candidates/{candidate['id']}/review",
        json={
            "action": "verify",
            "reviewed_by": "scientist",
            "note": "Reviewed for Phase 9 training",
        },
    )
    assert verified.status_code == 200, verified.text
    verified_candidate = verified.json()

    round_after = client.get(
        f"/api/v1/projects/{project['id']}/pose-active-learning-rounds",
        params={"video_id": video["id"]},
    ).json()[0]

    assert round_after["status"] == "complete"
    assert verified_candidate["review_status"] == "verified"

    return (
        project,
        video,
        track,
        round_after,
    )


def test_verified_pose_round_freezes_immutable_training_dataset(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, video, track, round_payload = _verified_round(
        client,
        monkeypatch,
    )

    created = client.post(
        f"/api/v1/pose-active-learning-rounds/{round_payload['id']}/training-dataset",
        json={
            "name": "Verified tentacle poses v1",
            "created_by": "scientist",
        },
    )
    assert created.status_code == 201, created.text

    dataset = created.json()

    assert dataset["status"] == "complete"
    assert dataset["item_count"] == 1
    assert dataset["schema_version"] == "pose-training-dataset-0001"
    assert len(dataset["manifest_sha256"]) == 64
    assert dataset["source_selection_sha256"] == round_payload["selection_sha256"]

    items_response = client.get(f"/api/v1/pose-training-datasets/{dataset['id']}/items")
    assert items_response.status_code == 200
    items = items_response.json()
    assert len(items) == 1

    frozen = items[0]

    assert frozen["video_id"] == video["id"]
    assert frozen["video_track_id"] == track["id"]
    assert len(frozen["verified_pose_sha256"]) == 64
    assert len(frozen["item_sha256"]) == 64
    assert frozen["review_provenance_json"]["actor"] == "scientist"

    frozen_pose = copy.deepcopy(frozen["canonical_pose_json"])

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        live_track = session.get(
            VideoTrack,
            str(track["id"]),
        )
        assert live_track is not None

        keyframes = copy.deepcopy(live_track.keyframes_json)
        selected_frame = frozen["frame_index"]

        for keyframe in keyframes:
            if int(keyframe["frame"]) != selected_frame:
                continue
            observations = keyframe.get("pose_observations")
            assert isinstance(
                observations,
                list,
            )
            observations[0]["x"] = float(observations[0]["x"]) + 25.0

        live_track.keyframes_json = keyframes
        live_track.revision += 1
        session.commit()

    frozen_again = client.get(f"/api/v1/pose-training-datasets/{dataset['id']}/items").json()[0]

    assert frozen_again["canonical_pose_json"] == frozen_pose
    assert frozen_again["item_sha256"] == frozen["item_sha256"]


def test_verified_pose_without_immutable_schema_is_rejected(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        _,
        _,
        _,
        round_payload,
    ) = _verified_round(
        client,
        monkeypatch,
        persist_schema=False,
    )

    response = client.post(
        f"/api/v1/pose-active-learning-rounds/{round_payload['id']}/training-dataset",
        json={},
    )

    assert response.status_code == 409

    assert "missing landmark schema" in response.text.lower()


def test_training_dataset_creation_is_idempotent_per_round(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, _, round_payload = _verified_round(
        client,
        monkeypatch,
    )

    path = f"/api/v1/pose-active-learning-rounds/{round_payload['id']}/training-dataset"

    first = client.post(
        path,
        json={},
    )
    second = client.post(
        path,
        json={},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["manifest_sha256"] == first.json()["manifest_sha256"]


def test_unreviewed_pose_round_cannot_become_training_truth(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(
        client,
        "Unreviewed pose dataset rejection",
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
    _build_temporal(
        client,
        str(track["id"]),
    )

    round_response = client.post(
        f"/api/v1/projects/{project['id']}/pose-active-learning-rounds",
        json={
            "name": "Still unreviewed",
            "video_id": video["id"],
            "track_ids": [track["id"]],
            "requested_size": 1,
            "minimum_frame_spacing": 0,
        },
    )
    assert round_response.status_code == 201

    response = client.post(
        f"/api/v1/pose-active-learning-rounds/{round_response.json()['id']}/training-dataset",
        json={},
    )

    assert response.status_code == 400
    assert "retraining-ready" in response.text


def test_training_dataset_blocks_pose_changed_after_verification(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, track, round_payload = _verified_round(
        client,
        monkeypatch,
    )

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        live_track = session.get(
            VideoTrack,
            str(track["id"]),
        )
        assert live_track is not None
        live_track.revision += 1
        session.commit()

    response = client.post(
        f"/api/v1/pose-active-learning-rounds/{round_payload['id']}/training-dataset",
        json={},
    )

    assert response.status_code == 409
    assert "changed after scientist verification" in (response.text)


def test_freeze_rejects_changed_candidate_acquisition_provenance(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Exercise the real reviewed-round API path before any dataset exists.
    # Editing the candidate's source metadata must not create frozen truth
    # under the original acquisition fingerprint.
    _, _, _, round_payload = _verified_round(client, monkeypatch)
    app = cast(FastAPI, client.app)

    with app.state.session_factory() as session:
        candidate = (
            session.query(PoseActiveLearningCandidate)
            .filter_by(round_id=str(round_payload["id"]))
            .one()
        )
        original_sha = candidate.provenance_sha256
        candidate.provenance_json = {
            **dict(candidate.provenance_json),
            "altered_after_review": True,
        }
        assert candidate.provenance_sha256 == original_sha
        session.commit()

    response = client.post(
        f"/api/v1/pose-active-learning-rounds/{round_payload['id']}/training-dataset",
        json={"name": "Must not freeze altered acquisition evidence"},
    )
    assert response.status_code == 409, response.text
    assert "acquisition provenance changed after selection" in response.text
    with app.state.session_factory() as session:
        assert session.query(PoseTrainingDataset).count() == 0


def test_native_pose_training_package_is_deterministic_and_verified_only(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, _, round_payload = _verified_round(
        client,
        monkeypatch,
    )

    dataset = client.post(
        f"/api/v1/pose-active-learning-rounds/{round_payload['id']}/training-dataset",
        json={},
    ).json()

    first = client.get(f"/api/v1/pose-training-datasets/{dataset['id']}/native-package")
    second = client.get(f"/api/v1/pose-training-datasets/{dataset['id']}/native-package")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.content == second.content
    assert (
        first.headers["x-reefvision-pose-dataset-package-sha256"]
        == second.headers["x-reefvision-pose-dataset-package-sha256"]
    )

    with zipfile.ZipFile(io.BytesIO(first.content)) as archive:
        names = set(archive.namelist())

        assert names == {
            "reefvision-pose-training-manifest.json",
            "items.jsonl",
            "README.txt",
            "SHA256SUMS",
        }

        manifest = json.loads(archive.read("reefvision-pose-training-manifest.json"))

        rows = [
            json.loads(line)
            for line in archive.read("items.jsonl").decode("utf-8").splitlines()
            if line.strip()
        ]

    assert manifest["truth_policy"] == "scientist_verified_only"
    assert manifest["pending_candidates_included"] is False
    assert manifest["skipped_candidates_included"] is False
    assert len(rows) == 1
    assert rows[0]["review_provenance"]["actor"] == "scientist"


def test_pose_training_dataset_rows_are_persisted(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, _, round_payload = _verified_round(
        client,
        monkeypatch,
    )

    dataset = client.post(
        f"/api/v1/pose-active-learning-rounds/{round_payload['id']}/training-dataset",
        json={},
    ).json()

    app = cast(FastAPI, client.app)

    with app.state.session_factory() as session:
        dataset_row = session.get(
            PoseTrainingDataset,
            dataset["id"],
        )
        assert dataset_row is not None

        item_rows = list(session.query(PoseTrainingDatasetItem).filter_by(dataset_id=dataset["id"]))

    assert len(item_rows) == 1
    assert (
        item_rows[0].verified_pose_sha256
        == dataset_row.manifest_json["items"][0]["verified_pose_sha256"]
    )
