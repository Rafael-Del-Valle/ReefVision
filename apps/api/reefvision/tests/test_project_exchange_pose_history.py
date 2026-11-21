"""Rebind validated pose-workflow history without rewriting checkpoint bytes."""

from copy import deepcopy
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    Job,
    ModelRegistration,
    Project,
    TrainingRun,
    WorkflowArtifact,
    WorkflowNodeRun,
    WorkflowRun,
)
from reefvision.domain.errors import ValidationError
from reefvision.services.project_exchange_pose_history import restore_pose_training_history
from reefvision.services.workflow_provenance import build_workflow_run_provenance
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.models import hash_model_file
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_project_exchange_pose_training_provenance import (
    completed_pose_study as completed_pose_study,
)


def _save_old_provenance(
    session: Session, artifact: WorkflowArtifact, payload: dict[str, Any]
) -> str:
    artifact.payload_json = payload
    artifact.payload_sha256 = canonical_json_sha256(payload)
    node = session.get(WorkflowNodeRun, artifact.producer_node_run_id)
    parent = session.get(WorkflowRun, artifact.workflow_run_id)
    assert node is not None and parent is not None and parent.job_id is not None
    job = session.get(Job, parent.job_id)
    assert job is not None
    node.result_json = {
        **node.result_json,
        "outputs": [
            {**item, "payload_sha256": artifact.payload_sha256}
            if item["artifact_id"] == artifact.id
            else item
            for item in node.result_json["outputs"]
        ],
    }
    provenance = build_workflow_run_provenance(session, run_id=parent.id)
    digest = canonical_json_sha256(provenance)
    parent.result_json = {
        **parent.result_json,
        "artifacts": [
            {**item, "payload_sha256": artifact.payload_sha256}
            if item["artifact_id"] == artifact.id
            else item
            for item in parent.result_json["artifacts"]
        ],
        "provenance_manifest": provenance,
        "provenance_sha256": digest,
    }
    job.result_json = {**(job.result_json or {}), "provenance_sha256": digest}
    return digest


def test_pose_history_restores_only_proven_pins_and_managed_paths(
    client: TestClient,
    test_settings: Settings,
    completed_pose_study: tuple[str, dict[str, Any], dict[str, Any], str],
) -> None:
    project_id, _, training, _ = completed_pose_study
    training_id = training["training_run_id"]
    registered = client.post(
        f"/api/v1/projects/{project_id}/models/register-from-run",
        json={"training_run_id": training_id},
    )
    assert registered.status_code == 200, registered.text

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        project = session.get(Project, project_id)
        run = session.get(TrainingRun, training_id)
        model = session.get(ModelRegistration, registered.json()["id"])
        assert project is not None and run is not None and model is not None
        assert run.result_checkpoint_path and run.job_id
        child = session.get(Job, run.job_id)
        assert child is not None and child.result_json is not None
        artifact = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.data_type == "training_result",
                WorkflowArtifact.payload_json["training_run_id"].as_string() == run.id,
            )
        )
        assert artifact is not None

        donor_root = f"projects/{uuid4()}"
        donor_checkpoint = donor_root + run.result_checkpoint_path.removeprefix(
            project.storage_root
        )
        assert donor_checkpoint != run.result_checkpoint_path
        source_dataset = canonical_json_sha256({"schema_version": "historical-dataset-fixture"})
        source_split = canonical_json_sha256(
            {
                **run.artifact_manifest_json["pose_split_manifest"],
                "training_dataset_manifest_sha256": source_dataset,
            }
        )
        pins = {
            "source_split_sha256": source_split,
            "source_dataset_sha256": source_dataset,
            "source_storage_root": donor_root,
            "target_storage_root": project.storage_root,
        }

        historical = deepcopy(artifact.payload_json)
        historical.update(
            dataset_manifest_sha256=source_dataset,
            split_manifest_sha256=source_split,
            result_checkpoint_path=donor_checkpoint,
            note={"original_dataset_hash": source_dataset},
        )
        historical["artifact_manifest"].update(
            pose_split_manifest_sha256=source_split,
            pose_training_dataset_manifest_sha256=source_dataset,
            best_checkpoint_path=donor_checkpoint,
        )
        model.metadata_json = {
            **model.metadata_json,
            "source_dataset_manifest_sha256": source_dataset,
            "source_split_manifest_sha256": source_split,
            "source_result_checkpoint_path": donor_checkpoint,
        }
        child.result_json = {**child.result_json, "result_checkpoint_path": donor_checkpoint}

        # All envelope checksums are valid. The training pin and path still need domain validation.
        for field, wrong_value in (
            ("split_manifest_sha256", canonical_json_sha256({"different": "training split"})),
            ("result_checkpoint_path", f"projects/{uuid4()}/training/best.pt"),
        ):
            unrelated = {**historical, field: wrong_value}
            _save_old_provenance(session, artifact, unrelated)
            expected_error = field if field == "split_manifest_sha256" else "project storage root"
            with pytest.raises(ValidationError, match=expected_error):
                restore_pose_training_history(session, run, **pins)
            assert artifact.payload_json == unrelated
            assert model.metadata_json["source_result_checkpoint_path"] == donor_checkpoint
            assert child.result_json["result_checkpoint_path"] == donor_checkpoint

        old_provenance = _save_old_provenance(session, artifact, historical)
        old_digest = artifact.payload_sha256
        updates = restore_pose_training_history(session, run, **pins)
        assert artifact.payload_sha256 == canonical_json_sha256(artifact.payload_json)
        assert updates[old_digest] == artifact.payload_sha256
        assert artifact.payload_json["dataset_manifest_sha256"] == run.dataset_manifest_sha256
        assert artifact.payload_json["split_manifest_sha256"] == run.split_manifest_sha256
        assert artifact.payload_json["result_checkpoint_path"] == run.result_checkpoint_path
        assert artifact.payload_json["note"] == {"original_dataset_hash": source_dataset}
        nested = artifact.payload_json["artifact_manifest"]
        assert nested["pose_split_manifest_sha256"] == run.split_manifest_sha256
        assert nested["pose_training_dataset_manifest_sha256"] == run.dataset_manifest_sha256
        assert nested["best_checkpoint_path"] == run.result_checkpoint_path
        assert model.metadata_json["source_split_manifest_sha256"] == run.split_manifest_sha256
        assert model.metadata_json["source_dataset_manifest_sha256"] == run.dataset_manifest_sha256
        assert model.metadata_json["source_result_checkpoint_path"] == run.result_checkpoint_path
        assert child.result_json["result_checkpoint_path"] == run.result_checkpoint_path

        parent = session.get(WorkflowRun, artifact.workflow_run_id)
        node = session.get(WorkflowNodeRun, artifact.producer_node_run_id)
        assert parent is not None and parent.job_id and node is not None
        job = session.get(Job, parent.job_id)
        assert job is not None and job.result_json is not None
        assert node.result_json["outputs"][0]["payload_sha256"] == artifact.payload_sha256
        parent_digest = canonical_json_sha256(
            build_workflow_run_provenance(session, run_id=parent.id)
        )
        assert (
            parent.result_json["provenance_sha256"]
            == job.result_json["provenance_sha256"]
            == parent_digest
        )
        assert updates[old_provenance] == parent_digest
        assert restore_pose_training_history(session, run, **pins) == {}
        checkpoint = resolve_managed_project_path(test_settings, run.result_checkpoint_path)
        assert hash_model_file(checkpoint)[0] == training["result_checkpoint_sha256"]
