"""Regression contract: every advertised workflow node must be plannable."""

from __future__ import annotations

from fastapi.testclient import TestClient

from reefvision.services.workflow_execution import EXECUTABLE_NODE_TYPES
from reefvision.services.workflow_graphs import _ACTIONS
from reefvision.services.workflow_node_registry_v1 import workflow_node_registry
from reefvision.services.workflow_runtime_adapters import (
    _ADAPTERS,
    RUNTIME_ADAPTER_NODE_TYPES,
)
from reefvision.tests.test_annotations import create_project


def test_extended_workflow_registry_has_planner_actions_and_runtime_dispatch() -> None:
    registry = workflow_node_registry()
    assert set(registry).issubset(_ACTIONS), "Advertised node missing planner action"
    advertised = {key for key, value in registry.items() if value.executable}
    assert advertised.issubset(EXECUTABLE_NODE_TYPES | RUNTIME_ADAPTER_NODE_TYPES)
    assert RUNTIME_ADAPTER_NODE_TYPES.issubset(_ADAPTERS)


def test_frozen_pose_dataset_node_plans_and_saves_as_versioned_graph(
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
    assert plan.json()["valid"] is True
    assert plan.json()["executable"] is True
    assert plan.json()["steps"][0]["node_type"] == "pose_training_dataset"

    saved = client.post(
        f"/api/v1/projects/{project['id']}/workflow-graphs",
        json={"graph": graph, "create_new_revision": True},
    )
    assert saved.status_code == 201, saved.text
    assert saved.json()["revision"] == 1
    assert len(saved.json()["graph_sha256"]) == 64
    queued = client.post(
        f"/api/v1/projects/{project['id']}/workflow-runs",
        json={"graph_record_id": saved.json()["id"]},
    )
    assert queued.status_code == 202, queued.text
    assert queued.json()["status"] == "queued"
    assert queued.json()["graph_sha256"] == saved.json()["graph_sha256"]
