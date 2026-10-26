"""Regression contract: every advertised workflow node must be plannable."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import Job, WorkflowGraphRecord
from reefvision.domain.errors import ValidationError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.workflow_execution import WorkflowRunCreateRequest
from reefvision.services.workflow_execution import EXECUTABLE_NODE_TYPES, WorkflowExecutionService
from reefvision.services.workflow_graphs import _ACTIONS
from reefvision.services.workflow_node_registry_v1 import workflow_node_registry
from reefvision.services.workflow_runtime_adapters import (
    _ADAPTERS,
    RUNTIME_ADAPTER_NODE_TYPES,
)
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_workflow_pose_training_phase10 import _frozen_dataset


def test_extended_workflow_registry_has_planner_actions_and_runtime_dispatch() -> None:
    registry = workflow_node_registry()
    assert set(registry).issubset(_ACTIONS), "Advertised node missing planner action"
    advertised = {key for key, value in registry.items() if value.executable}
    assert advertised.issubset(EXECUTABLE_NODE_TYPES | RUNTIME_ADAPTER_NODE_TYPES)
    assert RUNTIME_ADAPTER_NODE_TYPES.issubset(_ADAPTERS)


def test_frozen_pose_dataset_planner_rejects_nonexistent_dataset(
    client: TestClient,
) -> None:
    project = create_project(client, "Frozen pose workflow planner regression")
    graph = {
        "graph_id": "pose-dataset-source-regression",
        "name": "Frozen pose dataset source",
        "nodes": [
            {
                "node_id": "pose-dataset",
                "node_type": "pose_training_dataset",
                "parameters": {"dataset_id": "future-verified-dataset"},
            }
        ],
        "edges": [],
    }
    plan = client.post(f"/api/v1/projects/{project['id']}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["valid"] is False
    assert plan.json()["executable"] is False
    issue_codes = {issue["code"] for issue in plan.json()["issues"]}
    assert "pose_dataset_scope_mismatch" in issue_codes


def test_corrupt_saved_verified_pose_graph_finishes_as_failed(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Exercise the actual API-frozen, scientist-verified dataset and saved
    # workflow path, not a fabricated manifest or a standalone parser.
    project, dataset = _frozen_dataset(client, monkeypatch)
    project_id = str(project["id"])
    graph = {
        "graph_id": "track-e-invalid-persisted-pose-graph",
        "name": "Verified pose graph validation on dequeue",
        "nodes": [
            {
                "node_id": "frozen-pose",
                "node_type": "pose_training_dataset",
                "parameters": {
                    "dataset_id": str(dataset["id"]),
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
        record = session.get(WorkflowGraphRecord, str(saved.json()["id"]))
        assert record is not None
        # Simulate a malformed persisted graph after the valid run was queued.
        record.graph_json = {
            "schema_version": "workflow-graph-0001",
            "nodes": "not-a-node-list",
            "edges": [],
        }
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
    assert result["run"]["error_message"] == "Saved workflow graph revision is invalid"
    assert result["artifacts"] == []
    with app.state.session_factory() as session:
        job = session.get(Job, str(queued.json()["job_id"]))
        assert job is not None
        assert job.status == "failed"
        assert job.completed_at is not None

    # A still-parseable but modified saved revision must fail at queue time,
    # rather than producing a new run with already-invalid provenance.
    with app.state.session_factory() as session:
        record = session.get(WorkflowGraphRecord, str(saved.json()["id"]))
        assert record is not None
        record.graph_json = {**graph, "name": "Tampered verified pose graph"}
        session.commit()

    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="revision checksum"),
    ):
        WorkflowExecutionService(session).queue_run(
            project_id,
            WorkflowRunCreateRequest(graph_record_id=str(saved.json()["id"])),
        )
