from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.config import Settings
from reefvision.db.models import (
    PoseActiveLearningCandidate,
    PoseActiveLearningRound,
    PoseLandmarkSchema,
    PoseTrainingDataset,
    PoseTrainingDatasetItem,
)
from reefvision.jobs.project_exchange import (
    process_project_exchange_export_job,
)
from reefvision.services.pose_active_learning import (
    PoseActiveLearningService,
)
from reefvision.services.pose_training_datasets import (
    PoseTrainingDatasetService,
)
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_pose_training_datasets_phase9 import (
    _verified_round,
)


def _archive_with_pose_training_truth(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    bytes,
    dict[str, object],
    dict[str, object],
]:
    (
        project,
        _,
        _,
        round_payload,
    ) = _verified_round(
        client,
        monkeypatch,
    )

    dataset_response = client.post(
        f"/api/v1/pose-active-learning-rounds/{round_payload['id']}/training-dataset",
        json={
            "name": "Exchange frozen pose truth",
            "created_by": "scientist",
        },
    )

    assert dataset_response.status_code == 201, dataset_response.text

    dataset = dataset_response.json()

    created = client.post(
        f"/api/v1/projects/{project['id']}/exchange-packages",
        json={
            "include_media": True,
            "include_model_weights": False,
            "include_generated_artifacts": False,
            "notes": ("Phase 9C pose training truth exchange"),
        },
    )

    assert created.status_code == 202, created.text

    payload = created.json()

    app = cast(
        FastAPI,
        client.app,
    )

    assert process_project_exchange_export_job(
        test_settings,
        app.state.session_factory,
        payload["job_id"],
    )

    package_response = client.get(f"/api/v1/exchange-packages/{payload['package']['id']}")

    assert package_response.status_code == 200, package_response.text

    package = package_response.json()

    archive = (test_settings.resolved_data_dir / Path(package["archive_path"])).read_bytes()

    return (
        archive,
        project,
        dataset,
    )


def test_pose_training_truth_round_trips_through_project_exchange(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        archive,
        source_project,
        source_dataset,
    ) = _archive_with_pose_training_truth(
        client,
        test_settings,
        monkeypatch,
    )

    inspected = client.post(
        "/api/v1/exchange-packages/inspect",
        files={
            "file": (
                "pose-training.reefvision.zip",
                archive,
                "application/zip",
            )
        },
    )

    assert inspected.status_code == 200, inspected.text

    inspection = inspected.json()

    assert inspection["compatible"] is True

    expected_counts = {
        "pose_landmark_schemas": 1,
        "pose_landmark_schema_revisions": 1,
        "pose_active_learning_rounds": 1,
        "pose_landmark_corrections": 1,
        "pose_active_learning_candidates": 1,
        "pose_training_datasets": 1,
        "pose_training_dataset_items": 1,
    }

    for section, count in expected_counts.items():
        assert inspection["section_counts"][section] == count

    imported = client.post(
        "/api/v1/exchange-packages/import",
        files={
            "file": (
                "pose-training.reefvision.zip",
                archive,
                "application/zip",
            )
        },
        data={"project_name": ("Imported frozen pose truth")},
    )

    assert imported.status_code == 201, imported.text

    result = imported.json()

    imported_project_id = str(result["project_id"])

    assert imported_project_id != source_project["id"]

    for section, count in expected_counts.items():
        assert result["imported_counts"][section] == count

    app = cast(
        FastAPI,
        client.app,
    )

    with app.state.session_factory() as session:
        imported_dataset = session.scalar(
            select(PoseTrainingDataset).where(PoseTrainingDataset.project_id == imported_project_id)
        )

        assert imported_dataset is not None

        assert imported_dataset.id != source_dataset["id"]

        imported_round = session.get(
            PoseActiveLearningRound,
            imported_dataset.source_round_id,
        )

        assert imported_round is not None

        imported_candidate = session.scalar(
            select(PoseActiveLearningCandidate).where(
                PoseActiveLearningCandidate.round_id == imported_round.id
            )
        )

        assert imported_candidate is not None

        imported_item = session.scalar(
            select(PoseTrainingDatasetItem).where(
                PoseTrainingDatasetItem.dataset_id == imported_dataset.id
            )
        )

        assert imported_item is not None

        imported_schema = session.get(
            PoseLandmarkSchema,
            imported_dataset.pose_schema_id,
        )

        assert imported_schema is not None

        assert imported_item.candidate_id == imported_candidate.id

        assert imported_item.video_track_id == imported_candidate.video_track_id

        assert imported_dataset.pose_schema_id == imported_candidate.pose_schema_id

        assert imported_dataset.source_selection_sha256 == imported_round.selection_sha256

        assert imported_candidate.provenance_sha256 == canonical_json_sha256(
            dict(imported_candidate.provenance_json or {})
        )

        selection_identity = dict(imported_round.selection_manifest_json or {})

        selection_identity["schema_version"] = "pose-active-learning-selection-identity-0001"

        assert imported_round.selection_sha256 == canonical_json_sha256(selection_identity)

        retraining_manifest = (
            PoseActiveLearningService(session)
            .export_manifest(imported_round.id)
            .model_dump(mode="json")
        )

        assert imported_dataset.source_retraining_manifest_sha256 == canonical_json_sha256(
            retraining_manifest
        )

        assert (
            canonical_json_sha256(dict(imported_dataset.manifest_json))
            == imported_dataset.manifest_sha256
        )

        assert imported_dataset.manifest_json["dataset_id"] == imported_dataset.id

        assert imported_dataset.manifest_json["project_id"] == imported_project_id

        manifest_item = imported_dataset.manifest_json["items"][0]

        assert manifest_item["item_id"] == imported_item.id

        assert manifest_item["item_sha256"] == imported_item.item_sha256

        assert manifest_item["candidate_id"] == imported_candidate.id

        assert manifest_item["candidate_provenance_sha256"] == imported_candidate.provenance_sha256

        assert manifest_item["verified_pose_sha256"] == imported_candidate.verified_pose_sha256

        filename, package_bytes, package_sha = PoseTrainingDatasetService(session).native_package(
            imported_dataset.id
        )

        assert filename.endswith(".reefvision-pose.zip")

        assert package_bytes

        assert len(package_sha) == 64


def test_pose_training_exchange_inspection_detects_section_tampering(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        archive_bytes,
        _,
        _,
    ) = _archive_with_pose_training_truth(
        client,
        test_settings,
        monkeypatch,
    )

    source = io.BytesIO(archive_bytes)

    tampered = io.BytesIO()

    target_member = "records/pose_training_dataset_items.jsonl"

    with (
        zipfile.ZipFile(
            source,
            "r",
        ) as input_archive,
        zipfile.ZipFile(
            tampered,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as output_archive,
    ):
        for info in input_archive.infolist():
            content = input_archive.read(info.filename)

            if info.filename == target_member:
                content += b" \n"

            output_archive.writestr(
                info,
                content,
            )

    response = client.post(
        "/api/v1/exchange-packages/inspect",
        files={
            "file": (
                "tampered.reefvision.zip",
                tampered.getvalue(),
                "application/zip",
            )
        },
    )

    assert response.status_code == 200, response.text

    payload = response.json()

    assert payload["compatible"] is False

    assert any(
        ("section checksum failed: pose_training_dataset_items") in error.lower()
        for error in payload["errors"]
    )
