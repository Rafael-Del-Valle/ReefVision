"""Exercise a scientist-verified frozen pose dataset through saved workflow execution."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import PoseTrainingDataset
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_workflow_pose_training_phase10 import _frozen_dataset


def test_verified_pose_dataset_persists_workflow_lineage(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, dataset = _frozen_dataset(client, monkeypatch)
    project_id = str(project["id"])
    dataset_id = str(dataset["id"])
    graph = {
        "graph_id": "track-e-verified-pose-source",
        "name": "Verified pose dataset lineage",
        "nodes": [
            {
                "node_id": "frozen-pose",
                "node_type": "pose_training_dataset",
                "parameters": {
                    "dataset_id": dataset_id,
                    "manifest_sha256": dataset["manifest_sha256"],
                },
            }
        ],
        "edges": [],
    }

    other_project = create_project(client, "Pose dataset project isolation")
    forbidden = client.post(
        f"/api/v1/projects/{other_project['id']}/workflow-graphs/plan", json=graph
    )
    assert forbidden.status_code == 200, forbidden.text
    assert forbidden.json()["valid"] is False
    issue_codes = {issue["code"] for issue in forbidden.json()["issues"]}
    assert "pose_dataset_scope_mismatch" in issue_codes

    plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["valid"] is True
    assert plan.json()["executable"] is True

    stale_graph = {
        **graph,
        "nodes": [
            {
                **graph["nodes"][0],
                "parameters": {
                    "dataset_id": dataset_id,
                    "manifest_sha256": "0" * 64,
                },
            }
        ],
    }
    stale_plan = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=stale_graph
    )
    assert stale_plan.status_code == 200, stale_plan.text
    assert stale_plan.json()["valid"] is False
    assert stale_plan.json()["executable"] is False
    stale_codes = {issue["code"] for issue in stale_plan.json()["issues"]}
    assert "pose_dataset_manifest_mismatch" in stale_codes

    saved = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs",
        json={"graph": graph, "create_new_revision": True},
    )
    assert saved.status_code == 201, saved.text
    graph_record = saved.json()
    assert graph_record["revision"] == 1
    assert len(graph_record["graph_sha256"]) == 64

    queued = client.post(
        f"/api/v1/projects/{project_id}/workflow-runs",
        json={"graph_record_id": graph_record["id"]},
    )
    assert queued.status_code == 202, queued.text
    assert queued.json()["graph_sha256"] == graph_record["graph_sha256"]

    app = cast(FastAPI, client.app)
    assert (
        process_workflow_run_job(
            app.state.settings,
            app.state.session_factory,
            str(queued.json()["job_id"]),
        )
        is True
    )

    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert detail.status_code == 200, detail.text
    run = detail.json()
    assert run["run"]["status"] == "succeeded"
    assert run["run"]["graph_sha256"] == graph_record["graph_sha256"]
    assert run["run"]["workflow_graph_record_id"] == graph_record["id"]
    assert len(run["nodes"]) == 1
    assert run["nodes"][0]["status"] == "succeeded"

    outputs = [
        artifact
        for artifact in run["artifacts"]
        if artifact["data_type"] == "pose_training_dataset"
    ]
    assert len(outputs) == 1
    assert len(outputs[0]["payload_sha256"]) == 64
    assert outputs[0]["payload_sha256"] == canonical_json_sha256(outputs[0]["payload_json"])
    assert outputs[0]["workflow_run_id"] == run["run"]["id"]
    assert outputs[0]["producer_node_run_id"] == run["nodes"][0]["id"]
    assert outputs[0]["id"] in run["nodes"][0]["output_artifact_ids_json"]
    payload = outputs[0]["payload_json"]
    assert payload["project_id"] == project_id
    assert payload["dataset_id"] == dataset_id
    assert payload["manifest_sha256"] == dataset["manifest_sha256"]
    assert payload["pose_schema_id"] == dataset["pose_schema_id"]
    assert payload["pose_schema_revision"] == dataset["pose_schema_revision"]
    assert payload["pose_schema_content_hash"] == dataset["pose_schema_content_hash"]

    with app.state.session_factory() as session:
        frozen = session.get(PoseTrainingDataset, dataset_id)
        assert frozen is not None
        assert frozen.status == "complete"
        assert frozen.manifest_sha256 == payload["manifest_sha256"]
        assert frozen.pose_schema_content_hash == payload["pose_schema_content_hash"]


def test_frozen_pose_manifest_tampering_fails_saved_workflow_execution(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, dataset = _frozen_dataset(client, monkeypatch)
    project_id = str(project["id"])
    dataset_id = str(dataset["id"])
    graph = {
        "graph_id": "track-e-frozen-pose-integrity",
        "name": "Frozen pose manifest integrity at execution",
        "nodes": [
            {
                "node_id": "frozen-pose",
                "node_type": "pose_training_dataset",
                "parameters": {
                    "dataset_id": dataset_id,
                    "manifest_sha256": dataset["manifest_sha256"],
                },
            }
        ],
        "edges": [],
    }
    saved = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs",
        json={"graph": graph, "create_new_revision": True},
    )
    assert saved.status_code == 201, saved.text
    queued = client.post(
        f"/api/v1/projects/{project_id}/workflow-runs",
        json={"graph_record_id": saved.json()["id"]},
    )
    assert queued.status_code == 202, queued.text

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        frozen = session.get(PoseTrainingDataset, dataset_id)
        assert frozen is not None
        changed_manifest = dict(frozen.manifest_json)
        changed_manifest["truth_policy"] = "tampered_after_queue"
        frozen.manifest_json = changed_manifest
        session.commit()

    assert (
        process_workflow_run_job(
            app.state.settings,
            app.state.session_factory,
            str(queued.json()["job_id"]),
        )
        is False
    )
    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert detail.status_code == 200, detail.text
    result = detail.json()
    assert result["run"]["status"] == "failed"
    assert "manifest checksum" in result["run"]["error_message"]
    assert result["artifacts"] == []
