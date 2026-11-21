"""Verify that completed pose training retains its provenance through Project Exchange."""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from io import BytesIO
from typing import Any, cast
from unittest.mock import patch
from zipfile import ZipFile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response

from reefvision.config import Settings
from reefvision.db.models import TrainingRun
from reefvision.jobs.project_exchange import process_project_exchange_export_job
from reefvision.services import project_exchange_pose
from reefvision.services.pose_training_exports import PoseTrainingExportService
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.models import hash_model_file
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_pose_training_datasets_phase9 import _verified_round
from reefvision.tests.test_project_exchange_reefpose_workflow import _execute
from reefvision.tests.test_scientific_project_exchange import import_archive, rewrite
from reefvision.tests.test_workflow_pose_training_phase10 import (
    _native_pose_workflow_graph,
    _synthetic_exact_frames,
)

import_project_archive = cast(Callable[[TestClient, bytes], Response], import_archive)
rewrite_project_archive = cast(
    Callable[[bytes, Callable[[dict[str, Any], dict[str, Any]], None]], bytes], rewrite
)


def _freeze(client: TestClient, round_id: str) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/pose-active-learning-rounds/{round_id}/training-dataset",
        json={"created_by": "Exchange fixture reviewer"},
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


@pytest.fixture
def completed_pose_study(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, dict[str, Any], dict[str, Any], str]:
    # Reuse the existing synthetic decoder while the real native trainer writes its checkpoint.
    monkeypatch.setattr(
        PoseTrainingExportService, "_extract_exact_frames", staticmethod(_synthetic_exact_frames)
    )
    project, video, track, first_round = _verified_round(client, monkeypatch)
    project_id = str(project["id"])
    frozen = _freeze(client, str(first_round["id"]))

    # An authentic alternate freeze provides a competing source identity for the refusal test.
    second = client.post(
        f"/api/v1/projects/{project_id}/pose-active-learning-rounds",
        json={
            "name": "Alternate reviewed frames",
            "video_id": video["id"],
            "track_ids": [track["id"]],
            "requested_size": 2,
            "minimum_frame_spacing": 0,
        },
    )
    assert second.status_code == 201, second.text
    second_round_id = second.json()["id"]
    candidates = client.get(f"/api/v1/pose-active-learning-rounds/{second_round_id}/candidates")
    assert candidates.status_code == 200, candidates.text
    assert len(candidates.json()) == 2
    for candidate in candidates.json():
        reviewed = client.put(
            f"/api/v1/pose-active-learning-candidates/{candidate['id']}/review",
            json={"action": "verify", "reviewed_by": "Exchange fixture reviewer"},
        )
        assert reviewed.status_code == 200, reviewed.text
    alternate = _freeze(client, second_round_id)
    assert alternate["id"] != frozen["id"]
    assert alternate["manifest_sha256"] != frozen["manifest_sha256"]

    graph = _native_pose_workflow_graph(frozen["id"])
    nodes = cast(list[dict[str, Any]], graph["nodes"])
    edges = cast(list[dict[str, Any]], graph["edges"])
    graph["nodes"], graph["edges"] = nodes[:2], edges[:1]
    nodes[0]["parameters"]["manifest_sha256"] = frozen["manifest_sha256"]
    saved = client.post(f"/api/v1/projects/{project_id}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    detail = _execute(client, project_id, saved.json()["id"])
    assert detail["run"]["status"] == "succeeded", detail["run"]["error_message"]
    [training] = [
        artifact["payload_json"]
        for artifact in detail["artifacts"]
        if artifact["data_type"] == "training_result"
    ]
    return project_id, frozen, training, cast(str, alternate["id"])


def _archive(
    client: TestClient, settings: Settings, project_id: str, *, weights: bool = True
) -> bytes:
    queued = client.post(
        f"/api/v1/projects/{project_id}/exchange-packages",
        json={
            "include_media": True,
            "include_model_weights": weights,
            "include_generated_artifacts": True,
        },
    )
    assert queued.status_code == 202, queued.text
    exported = queued.json()
    app = cast(FastAPI, client.app)
    assert process_project_exchange_export_job(
        settings, app.state.session_factory, exported["job_id"]
    )
    downloaded = client.get(f"/api/v1/exchange-packages/{exported['package']['id']}/download")
    assert downloaded.status_code == 200, downloaded.text
    return cast(bytes, downloaded.content)


def _restore(client: TestClient, archive: bytes) -> tuple[str, dict[str, str]]:
    restored = import_project_archive(client, archive)
    assert restored.status_code == 201, restored.text
    receipt = restored.json()
    return receipt["project_id"], receipt["package"]["options_json"]["id_map"]


def _assert_registration_unavailable(client: TestClient, project_id: str, training_id: str) -> str:
    read = client.get(f"/api/v1/training-runs/{training_id}")
    assert read.status_code == 200, read.text
    assert read.json()["registered_model_id"] is None
    registration = client.post(
        f"/api/v1/projects/{project_id}/models/register-from-run",
        json={"training_run_id": training_id},
    )
    assert registration.status_code in {400, 404, 409}, registration.text
    models = client.get(f"/api/v1/projects/{project_id}/models")
    assert models.status_code == 200, models.text
    assert models.json() == []
    return cast(str, registration.json()["detail"]).lower()


def _assert_pose_registration(
    client: TestClient,
    test_settings: Settings,
    project: str,
    run_id: str,
    dataset_id: str,
    original_hash: str,
    source_schema_digest: str,
) -> str:
    read = client.get(f"/api/v1/training-runs/{run_id}")
    assert read.status_code == 200, read.text
    run = read.json()
    assert run["status"] == "completed"
    assert run["registered_model_id"] is None
    restored_checkpoint = resolve_managed_project_path(test_settings, run["result_checkpoint_path"])
    assert hash_model_file(restored_checkpoint)[0] == original_hash

    registration = client.post(
        f"/api/v1/projects/{project}/models/register-from-run",
        json={"training_run_id": run_id},
    )
    assert registration.status_code == 200, registration.text
    model = registration.json()
    assert model["sha256"] == original_hash
    assert (
        hash_model_file(resolve_managed_project_path(test_settings, model["managed_path"]))[0]
        == original_hash
    )

    dataset_response = client.get(f"/api/v1/pose-training-datasets/{dataset_id}")
    assert dataset_response.status_code == 200, dataset_response.text
    dataset = dataset_response.json()
    metadata = model["metadata_json"]
    assert metadata["source_training_run_id"] == run_id
    assert metadata["source_pose_training_dataset_id"] == dataset_id
    assert metadata["source_pose_training_dataset_manifest_sha256"] == dataset["manifest_sha256"]
    assert metadata["pose_landmark_schema"]["schema_id"] == dataset["pose_schema_id"]
    assert metadata["pose_landmark_schema"]["schema_revision"] == dataset["pose_schema_revision"]
    assert metadata["pose_landmark_schema"]["content_hash"] == source_schema_digest
    assert (
        client.get(f"/api/v1/training-runs/{run_id}").json()["registered_model_id"] == model["id"]
    )
    return cast(str, model["id"])


def test_real_native_checkpoint_registers_after_two_fresh_project_transfers(
    client: TestClient,
    test_settings: Settings,
    completed_pose_study: tuple[str, dict[str, Any], dict[str, Any], str],
) -> None:
    source, frozen, training, _ = completed_pose_study
    source_run = training["training_run_id"]
    source_dataset = frozen["id"]
    checkpoint = resolve_managed_project_path(test_settings, training["result_checkpoint_path"])
    original_hash = hash_model_file(checkpoint)[0]
    assert original_hash == training["result_checkpoint_sha256"]

    first, first_map = _restore(client, _archive(client, test_settings, source))
    second, second_map = _restore(client, _archive(client, test_settings, first))
    first_run, first_dataset = first_map[source_run], first_map[source_dataset]
    second_run, second_dataset = second_map[first_run], second_map[first_dataset]
    assert len({source, first, second}) == len({source_run, first_run, second_run}) == 3

    registrations = []
    for project, run_id, dataset_id in (
        (source, source_run, source_dataset),
        (first, first_run, first_dataset),
        (second, second_run, second_dataset),
    ):
        registrations.append(
            _assert_pose_registration(
                client,
                test_settings,
                project,
                run_id,
                dataset_id,
                original_hash,
                frozen["pose_schema_content_hash"],
            )
        )
    assert len(set(registrations)) == 3
    assert hash_model_file(checkpoint)[0] == original_hash


def test_legacy_pose_exchange_reexports_before_first_registration(
    client: TestClient,
    test_settings: Settings,
    completed_pose_study: tuple[str, dict[str, Any], dict[str, Any], str],
) -> None:
    source, frozen, training, _ = completed_pose_study
    source_archive = _archive(client, test_settings, source)
    # Simulate the previous importer while preserving every other import step.
    with patch.object(
        project_exchange_pose, "rebind_pose_training_run", return_value=None, create=True
    ):
        legacy, legacy_map = _restore(client, source_archive)
    legacy_run_id = legacy_map[training["training_run_id"]]
    legacy_dataset_id = legacy_map[frozen["id"]]
    original_hash = training["result_checkpoint_sha256"]
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        run = session.get(TrainingRun, legacy_run_id)
        assert run is not None and run.project_id == legacy
        assert run.registered_model_id is None and run.result_checkpoint_path
        split = run.artifact_manifest_json["pose_split_manifest"]
        assert canonical_json_sha256(split) != run.split_manifest_sha256
        path = resolve_managed_project_path(test_settings, run.result_checkpoint_path)
        assert hash_model_file(path)[0] == original_hash

    reexported = _archive(client, test_settings, legacy)
    reexported_project, rebound_map = _restore(client, reexported)
    registered_legacy = _assert_pose_registration(
        client,
        test_settings,
        legacy,
        legacy_run_id,
        legacy_dataset_id,
        original_hash,
        frozen["pose_schema_content_hash"],
    )
    registered_reexport = _assert_pose_registration(
        client,
        test_settings,
        reexported_project,
        rebound_map[legacy_run_id],
        rebound_map[legacy_dataset_id],
        original_hash,
        frozen["pose_schema_content_hash"],
    )
    assert registered_legacy != registered_reexport


def test_pose_training_exchange_without_checkpoint_retains_readable_run(
    client: TestClient,
    test_settings: Settings,
    completed_pose_study: tuple[str, dict[str, Any], dict[str, Any], str],
) -> None:
    source, _, training, _ = completed_pose_study
    archive = _archive(client, test_settings, source, weights=False)
    with ZipFile(BytesIO(archive)) as package:
        assert training["result_checkpoint_sha256"] not in {
            sha256(package.read(name)).hexdigest() for name in package.namelist()
        }
    destination, mapping = _restore(client, archive)
    diagnostic = _assert_registration_unavailable(
        client, destination, mapping[training["training_run_id"]]
    )
    assert "checkpoint" in diagnostic or "weight" in diagnostic


def test_pose_training_exchange_does_not_reseal_an_inconsistent_source(
    client: TestClient,
    test_settings: Settings,
    completed_pose_study: tuple[str, dict[str, Any], dict[str, Any], str],
) -> None:
    source, frozen, training, alternate_id = completed_pose_study
    training_id = training["training_run_id"]

    def choose_inconsistent_split(_manifest: dict[str, Any], sections: dict[str, Any]) -> None:
        [alternate] = [
            dataset
            for dataset in sections["pose_training_datasets"]
            if dataset["id"] == alternate_id
        ]
        [run] = [row for row in sections["training_runs"] if row["id"] == training_id]
        artifact = run["artifact_manifest_json"]
        split = artifact["pose_split_manifest"]
        assert split["training_dataset_id"] == frozen["id"]
        split["training_dataset_id"] = alternate["id"]
        split["training_dataset_manifest_sha256"] = alternate["manifest_sha256"]
        # The split has internally consistent bytes but disagrees with the archived run's source.
        split_hash = canonical_json_sha256(split)
        run["split_manifest_sha256"] = split_hash
        artifact["pose_split_manifest_sha256"] = split_hash

    before = {item["id"] for item in client.get("/api/v1/projects").json()}
    damaged = rewrite_project_archive(
        _archive(client, test_settings, source), choose_inconsistent_split
    )
    imported = import_project_archive(client, damaged)
    if imported.status_code == 400:
        assert {item["id"] for item in client.get("/api/v1/projects").json()} == before
        return
    assert imported.status_code == 201, imported.text
    receipt = imported.json()
    mapping = receipt["package"]["options_json"]["id_map"]
    diagnostic = _assert_registration_unavailable(
        client, receipt["project_id"], mapping[training_id]
    )
    assert any(token in diagnostic for token in ("provenance", "manifest", "checkpoint", "dataset"))
