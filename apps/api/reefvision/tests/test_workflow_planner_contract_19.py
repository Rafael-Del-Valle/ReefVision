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
    assert any(
        issue["code"] == "pose_dataset_scope_mismatch"
        for issue in plan.json()["issues"]
    )
