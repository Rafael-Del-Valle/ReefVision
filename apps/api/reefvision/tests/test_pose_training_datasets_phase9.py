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
    PoseActiveLearningRound,
    PoseLandmarkCorrection,
    PoseLandmarkObservation,
    PoseLandmarkSchema,
    PoseLandmarkSchemaRevision,
    PoseLandmarkTrack,
    PoseTrainingDataset,
    PoseTrainingDatasetItem,
    VideoAsset,
    VideoTrack,
)
from reefvision.services.pose_training_datasets import frozen_pose_item_evidence_sha256
from reefvision.storage.datasets import canonical_json_sha256
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
    # Repeating a freeze must not create duplicate immutable item rows.
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        datasets = session.query(PoseTrainingDataset).all()
        assert len(datasets) == 1
        dataset_id = first.json()["id"]
        items = session.query(PoseTrainingDatasetItem).filter_by(dataset_id=dataset_id).all()
        assert len(items) == first.json()["item_count"]
        assert len(items) > 0


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


@pytest.mark.parametrize("changed_record", ["correction", "candidate", "timestamp"])
def test_freeze_rejects_changed_scientist_review_attribution(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    changed_record: str,
) -> None:
    # Exercise the actual scientist-review API path, then corrupt one of its
    # independently persisted audit records before freezing any training data.
    _, _, _, round_payload = _verified_round(client, monkeypatch)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        candidate = (
            session.query(PoseActiveLearningCandidate)
            .filter_by(round_id=str(round_payload["id"]))
            .one()
        )
        correction = session.get(PoseLandmarkCorrection, candidate.correction_id)
        assert correction is not None
        assert correction.actor == candidate.reviewed_by == "scientist"
        if changed_record == "correction":
            correction.actor = "different-reviewer"
        elif changed_record == "candidate":
            candidate.reviewed_by = "different-reviewer"
        else:
            candidate.reviewed_at = None
        session.commit()

    response = client.post(
        f"/api/v1/pose-active-learning-rounds/{round_payload['id']}/training-dataset",
        json={},
    )
    assert response.status_code == 409, response.text
    assert "scientist review attribution changed" in response.text
    with app.state.session_factory() as session:
        assert session.query(PoseTrainingDataset).count() == 0


@pytest.mark.parametrize(
    "changed_field",
    ["source_track_revision", "candidate_provenance_sha256", "verified_pose_sha256"],
)
def test_freeze_rejects_modified_scientist_correction_evidence(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    changed_field: str,
) -> None:
    # Reuse a real saved scientist-verification round, not a synthetic
    # correction: independently altered audit evidence must block freezing.
    _, _, _, round_payload = _verified_round(client, monkeypatch)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        candidate = (
            session.query(PoseActiveLearningCandidate)
            .filter_by(round_id=str(round_payload["id"]))
            .one()
        )
        correction = session.get(PoseLandmarkCorrection, candidate.correction_id)
        assert correction is not None
        if changed_field == "verified_pose_sha256":
            after = dict(correction.after_json)
            after[changed_field] = "0" * 64
            correction.after_json = after
        else:
            before = dict(correction.before_json)
            before[changed_field] = -1 if changed_field == "source_track_revision" else "0" * 64
            correction.before_json = before
        session.commit()

    response = client.post(
        f"/api/v1/pose-active-learning-rounds/{round_payload['id']}/training-dataset",
        json={},
    )
    assert response.status_code == 409, response.text
    assert "scientist correction evidence changed" in response.text
    with app.state.session_factory() as session:
        assert session.query(PoseTrainingDataset).count() == 0


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


@pytest.mark.parametrize(
    ("field", "replacement", "expected_error"),
    [
        ("video_sha256", None, "Source video checksum changed after acquisition"),
        ("video_id", "wrong-video", "does not match verified source"),
        ("video_track_id", "wrong-track", "does not match verified source"),
        ("focus_frame", -1, "does not match verified source"),
    ],
)
def test_freeze_rejects_resigned_acquisition_with_invalid_source_identity(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    replacement: object,
    expected_error: str,
) -> None:
    # Use a real verified round and re-sign the candidate's acquisition
    # evidence. A frozen dataset must be valid on its first read, even when
    # the candidate digest has been updated to match corrupted source IDs.
    _, _, _, round_payload = _verified_round(client, monkeypatch)
    app = cast(FastAPI, client.app)

    with app.state.session_factory() as session:
        candidate = (
            session.query(PoseActiveLearningCandidate)
            .filter_by(round_id=str(round_payload["id"]))
            .one()
        )
        acquisition = dict(candidate.provenance_json)
        assert field in acquisition
        if replacement is None:
            acquisition.pop(field)
        else:
            acquisition[field] = replacement
        candidate.provenance_json = acquisition
        candidate.provenance_sha256 = canonical_json_sha256(acquisition)
        session.commit()

    response = client.post(
        f"/api/v1/pose-active-learning-rounds/{round_payload['id']}/training-dataset",
        json={"name": "Must not freeze invalid source identity"},
    )
    assert response.status_code == 409, response.text
    assert expected_error in response.text
    with app.state.session_factory() as session:
        assert session.query(PoseTrainingDataset).count() == 0


@pytest.mark.parametrize("resign_selection", [False, True])
def test_freeze_rejects_changed_saved_selection_lineage(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    resign_selection: bool,
) -> None:
    # Reuse a real completed scientist-review round, not a fabricated dataset.
    # Both an unsigned selection edit and a re-signed selection with identities
    # that disagree with its persisted candidates must fail before freezing.
    _, _, _, round_payload = _verified_round(client, monkeypatch)
    app = cast(FastAPI, client.app)

    with app.state.session_factory() as session:
        round_record = session.get(PoseActiveLearningRound, str(round_payload["id"]))
        assert round_record is not None
        selection = copy.deepcopy(round_record.selection_manifest_json)
        selection["items"][0]["focus_frame"] = -1
        round_record.selection_manifest_json = selection
        if resign_selection:
            identity = {
                **selection,
                "schema_version": "pose-active-learning-selection-identity-0001",
            }
            round_record.selection_sha256 = canonical_json_sha256(identity)
        session.commit()

    response = client.post(
        f"/api/v1/pose-active-learning-rounds/{round_payload['id']}/training-dataset",
        json={"name": "Reject changed saved selection"},
    )
    assert response.status_code == 409, response.text
    expected = (
        "selected candidate identities changed"
        if resign_selection
        else "selection manifest checksum changed"
    )
    assert expected in response.text
    with app.state.session_factory() as session:
        assert session.query(PoseTrainingDataset).count() == 0


def test_freeze_rejects_blank_video_digest_even_when_acquisition_agrees(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A re-signed acquisition and a damaged source video can both carry an
    # empty checksum. Equality alone does not establish scientific lineage.
    _, video, _, round_payload = _verified_round(client, monkeypatch)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        source = session.get(VideoAsset, str(video["id"]))
        assert source is not None and source.sha256
        source.sha256 = ""
        candidate = (
            session.query(PoseActiveLearningCandidate)
            .filter_by(round_id=str(round_payload["id"]))
            .one()
        )
        acquisition = {**candidate.provenance_json, "video_sha256": ""}
        candidate.provenance_json = acquisition
        candidate.provenance_sha256 = canonical_json_sha256(acquisition)
        session.commit()

    response = client.post(
        f"/api/v1/pose-active-learning-rounds/{round_payload['id']}/training-dataset",
        json={},
    )
    assert response.status_code == 409, response.text
    assert "Source video checksum changed after acquisition" in response.text
    with app.state.session_factory() as session:
        assert session.query(PoseTrainingDataset).count() == 0


@pytest.mark.parametrize("schema_location", ["dataset", "manifest"])
def test_frozen_dataset_rejects_resigned_incompatible_schema_version(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    schema_location: str,
) -> None:
    _, _, _, round_payload = _verified_round(client, monkeypatch)
    response = client.post(
        f"/api/v1/pose-active-learning-rounds/{round_payload['id']}/training-dataset",
        json={},
    )
    assert response.status_code == 201, response.text
    dataset_id = response.json()["id"]
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        dataset = session.get(PoseTrainingDataset, dataset_id)
        assert dataset is not None
        if schema_location == "dataset":
            dataset.schema_version = "pose-training-dataset-unsupported"
        else:
            manifest = copy.deepcopy(dataset.manifest_json)
            manifest["schema_version"] = "pose-training-dataset-manifest-unsupported"
            dataset.manifest_json = manifest
            dataset.manifest_sha256 = canonical_json_sha256(manifest)
        session.commit()

    response = client.get(f"/api/v1/pose-training-datasets/{dataset_id}/manifest")
    assert response.status_code == 409, response.text
    assert "manifest lineage" in response.text


def test_frozen_dataset_rejects_resigned_blank_video_digest(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Exercise an actual scientist-verified frozen dataset, then re-sign its
    # persisted manifest and review evidence around a missing video digest.
    _, _, _, round_payload = _verified_round(client, monkeypatch)
    response = client.post(
        f"/api/v1/pose-active-learning-rounds/{round_payload['id']}/training-dataset",
        json={},
    )
    assert response.status_code == 201, response.text
    dataset_id = response.json()["id"]
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        dataset = session.get(PoseTrainingDataset, dataset_id)
        assert dataset is not None
        item = session.query(PoseTrainingDatasetItem).filter_by(dataset_id=dataset_id).one()
        item.video_sha256 = ""
        acquisition = {**item.acquisition_provenance_json, "video_sha256": ""}
        item.acquisition_provenance_json = acquisition
        review = copy.deepcopy(item.review_provenance_json)
        review["before"]["candidate_provenance_sha256"] = canonical_json_sha256(acquisition)
        item.review_provenance_json = review
        manifest = copy.deepcopy(dataset.manifest_json)
        summary = manifest["items"][0]
        summary["video_sha256"] = ""
        summary["candidate_provenance_sha256"] = canonical_json_sha256(acquisition)
        summary["frozen_evidence_sha256"] = frozen_pose_item_evidence_sha256(item)
        dataset.manifest_json = manifest
        dataset.manifest_sha256 = canonical_json_sha256(manifest)
        session.commit()

    response = client.get(f"/api/v1/pose-training-datasets/{dataset_id}/manifest")
    assert response.status_code == 409, response.text
    assert "item lineage" in response.text


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
        == hashlib.sha256(first.content).hexdigest()
    )
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

        # Validate the exported checksum index against the actual package bytes,
        # rather than only comparing two ZIP downloads from the same code path.
        checksum_lines = archive.read("SHA256SUMS").decode("ascii").splitlines()
        indexed_files = {}
        for line in checksum_lines:
            digest, separator, filename = line.partition("  ")
            assert separator and len(digest) == 64
            assert filename in names and filename != "SHA256SUMS"
            assert filename not in indexed_files
            assert hashlib.sha256(archive.read(filename)).hexdigest() == digest
            indexed_files[filename] = digest
        assert set(indexed_files) == names - {"SHA256SUMS"}

    assert manifest["truth_policy"] == "scientist_verified_only"
    assert manifest["pending_candidates_included"] is False
    assert manifest["skipped_candidates_included"] is False
    assert len(rows) == 1
    assert rows[0]["review_provenance"]["actor"] == "scientist"

    # Exercise the *persisted* scientist-verified dataset, not an artificial
    # item fixture. Even if both the review fingerprint and manifest are
    # re-signed, source video identity must remain bound to the frozen row.
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        dataset_row = session.get(PoseTrainingDataset, dataset["id"])
        assert dataset_row is not None
        item = session.query(PoseTrainingDatasetItem).filter_by(dataset_id=dataset["id"]).one()
        source = copy.deepcopy(item.acquisition_provenance_json)
        assert source["video_sha256"] == item.video_sha256
        source["video_sha256"] = "0" * 64 if item.video_sha256 != "0" * 64 else "1" * 64
        item.acquisition_provenance_json = source

        review = copy.deepcopy(item.review_provenance_json)
        review["before"]["candidate_provenance_sha256"] = canonical_json_sha256(source)
        item.review_provenance_json = review

        manifest = copy.deepcopy(dataset_row.manifest_json)
        manifest["items"][0]["candidate_provenance_sha256"] = canonical_json_sha256(source)
        manifest["items"][0]["frozen_evidence_sha256"] = frozen_pose_item_evidence_sha256(item)
        dataset_row.manifest_json = manifest
        dataset_row.manifest_sha256 = canonical_json_sha256(manifest)
        session.commit()

    tampered_export = client.get(f"/api/v1/pose-training-datasets/{dataset['id']}/native-package")
    assert tampered_export.status_code == 409, tampered_export.text
    assert "item lineage" in tampered_export.text


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


def test_freeze_rejects_nonlist_canonical_keyframes_without_persisting_dataset(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The persisted scientist review remains valid, but corrupted source
    # keyframes cannot be treated as a training-ready canonical pose.
    _, _, track, round_payload = _verified_round(client, monkeypatch)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        source = session.get(VideoTrack, str(track["id"]))
        assert source is not None
        assert isinstance(source.keyframes_json, list)
        source.keyframes_json = {"frame": 0}
        session.commit()

    response = client.post(
        f"/api/v1/pose-active-learning-rounds/{round_payload['id']}/training-dataset",
        json={"name": "Must reject malformed canonical keyframes"},
    )
    assert response.status_code == 409, response.text
    assert "keyframes must be a list" in response.text
    with app.state.session_factory() as session:
        assert session.query(PoseTrainingDataset).count() == 0


def test_freeze_rejects_duplicate_canonical_frame_without_persisting_dataset(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Start with an actually persisted, scientist-verified Active Learning round.
    # A duplicated canonical frame must not be chosen by JSON list order.
    _, _, track, round_payload = _verified_round(client, monkeypatch)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        source = session.get(VideoTrack, str(track["id"]))
        assert source is not None
        frames = copy.deepcopy(source.keyframes_json)
        assert isinstance(frames, list) and frames
        candidate = (
            session.query(PoseActiveLearningCandidate)
            .filter_by(round_id=str(round_payload["id"]))
            .one()
        )
        matching = [
            frame
            for frame in frames
            if isinstance(frame, dict) and frame.get("frame") == candidate.focus_frame
        ]
        assert len(matching) == 1
        frames.append(copy.deepcopy(matching[0]))
        source.keyframes_json = frames
        session.commit()

    response = client.post(
        f"/api/v1/pose-active-learning-rounds/{round_payload['id']}/training-dataset",
        json={"name": "Must reject ambiguous canonical frame"},
    )
    assert response.status_code == 409, response.text
    assert "exactly once" in response.text
    with app.state.session_factory() as session:
        assert session.query(PoseTrainingDataset).count() == 0


@pytest.mark.parametrize("field", ["pose_observations", "keypoints", "bbox"])
def test_freeze_rejects_nonlist_canonical_landmarks_without_persisting_dataset(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    # A completed scientist review must not make a subsequently corrupted
    # canonical landmark collection eligible for frozen training.
    _, _, track, round_payload = _verified_round(client, monkeypatch)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        source = session.get(VideoTrack, str(track["id"]))
        assert source is not None
        frames = copy.deepcopy(source.keyframes_json)
        assert isinstance(frames, list)
        candidate = (
            session.query(PoseActiveLearningCandidate)
            .filter_by(round_id=str(round_payload["id"]))
            .one()
        )
        matching = [
            frame
            for frame in frames
            if isinstance(frame, dict)
            and type(frame.get("frame")) is int
            and frame["frame"] == candidate.focus_frame
        ]
        assert len(matching) == 1
        matching[0][field] = {"unexpected": "mapping"}
        source.keyframes_json = frames
        session.commit()

    response = client.post(
        f"/api/v1/pose-active-learning-rounds/{round_payload['id']}/training-dataset",
        json={"name": "Reject malformed canonical landmarks"},
    )
    assert response.status_code == 409, response.text
    expected = "canonical pose bbox must be a list" if field == "bbox" else "canonical pose landmarks must be lists"
    assert expected in response.text
    with app.state.session_factory() as session:
        assert session.query(PoseTrainingDataset).count() == 0
