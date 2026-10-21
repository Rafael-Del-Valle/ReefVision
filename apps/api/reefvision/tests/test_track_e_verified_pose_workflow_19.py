"""Exercise a scientist-verified frozen pose dataset through saved workflow execution."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import PoseTrainingDataset
from reefvision.jobs.workflow import process_workflow_run_job
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
                "parameters": {"dataset_id": dataset_id},
            }
        ],
        "edges": [],
    }

    plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["valid"] is True
    assert plan.json()["executable"] is True

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
    assert len(run["nodes"]) == 1
    assert run["nodes"][0]["status"] == "succeeded"

    outputs = [
        artifact
        for artifact in run["artifacts"]
        if artifact["data_type"] == "pose_training_dataset"
    ]
    assert len(outputs) == 1
    assert len(outputs[0]["payload_sha256"]) == 64
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
