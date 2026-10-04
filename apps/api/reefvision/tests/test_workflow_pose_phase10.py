from __future__ import annotations

from fastapi.testclient import TestClient

from reefvision.services.workflow_runtime_adapters import (
    RUNTIME_ADAPTER_NODE_TYPES,
)
from reefvision.tests.test_annotations import create_project

_EXECUTABLE_PHASE10_NODES = {
    "pose_inference",
    "pose_temporal_association",
    "behavior_dynamics",
    "pose_active_learning",
    "pose_training_dataset_freeze",
    "pose_training_export",
}

_PHASE10_REVIEW_GATES = {
    "pose_review_gate",
    "pose_active_learning_review_gate",
}

_PHASE10_POSE_NODES = _EXECUTABLE_PHASE10_NODES | _PHASE10_REVIEW_GATES


def test_phase10_pose_workflow_contracts_are_registered(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/workflow-graphs/node-registry")
    assert response.status_code == 200, response.text

    registry = {item["node_type"]: item for item in response.json()}

    assert _PHASE10_POSE_NODES.issubset(registry)

    for node_type in _EXECUTABLE_PHASE10_NODES:
        assert registry[node_type]["executable"] is True
        assert registry[node_type]["execution_state"] == "executable_pose_workflow"

    for node_type in _PHASE10_REVIEW_GATES:
        assert registry[node_type]["executable"] is False
        assert registry[node_type]["execution_state"] == "contract_only_phase10a"

    assert _EXECUTABLE_PHASE10_NODES.issubset(RUNTIME_ADAPTER_NODE_TYPES)

    pose = registry["pose_inference"]
    assert {item["port_id"] for item in pose["input_ports"]} == {
        "video",
        "model",
    }
    assert pose["output_ports"][0]["accepted_types"] == ["pose_tracks"]

    temporal = registry["pose_temporal_association"]
    assert temporal["input_ports"][0]["accepted_types"] == ["pose_tracks"]
    assert temporal["output_ports"][0]["accepted_types"] == ["pose_temporal_tracks"]

    review = registry["pose_review_gate"]
    assert review["input_ports"][0]["accepted_types"] == ["pose_temporal_tracks"]
    assert review["output_ports"][0]["accepted_types"] == ["reviewed_pose_tracks"]

    behavior = registry["behavior_dynamics"]
    assert behavior["required_parameters"] == ["ethogram_revision_id"]

    freeze = registry["pose_training_dataset_freeze"]
    assert freeze["output_ports"][0]["accepted_types"] == ["pose_training_dataset"]

    export = registry["pose_training_export"]
    assert export["optional_parameters"]["format"] == "native"


def test_phase10_behavior_requires_reviewed_pose_truth(
    client: TestClient,
) -> None:
    project = create_project(
        client,
        "Phase 10 reviewed pose requirement",
    )

    graph = {
        "graph_id": "pose-review-type-safety",
        "name": "Pose review type safety",
        "nodes": [
            {
                "node_id": "temporal",
                "node_type": ("pose_temporal_association"),
            },
            {
                "node_id": "behavior",
                "node_type": "behavior_dynamics",
                "parameters": {
                    "ethogram_revision_id": ("ethogram-test"),
                },
            },
        ],
        "edges": [
            {
                "edge_id": "unreviewed-to-behavior",
                "source_node_id": "temporal",
                "source_port_id": "tracks",
                "target_node_id": "behavior",
                "target_port_id": "poses",
            }
        ],
    }

    response = client.post(
        (f"/api/v1/projects/{project['id']}/workflow-graphs/validate"),
        json=graph,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["valid"] is False

    issues = payload["issues"]

    assert any(
        item["code"] == "incompatible_port_types" and item["edge_id"] == ("unreviewed-to-behavior")
        for item in issues
    )


def test_phase10_pose_review_gate_has_type_safe_scientist_boundary(
    client: TestClient,
) -> None:
    project = create_project(
        client,
        "Phase 10 scientist boundary",
    )

    graph = {
        "graph_id": "pose-review-boundary",
        "name": "Pose scientist review boundary",
        "nodes": [
            {
                "node_id": "temporal",
                "node_type": ("pose_temporal_association"),
            },
            {
                "node_id": "review",
                "node_type": "pose_review_gate",
            },
            {
                "node_id": "behavior",
                "node_type": "behavior_dynamics",
                "parameters": {
                    "ethogram_revision_id": ("ethogram-test"),
                },
            },
        ],
        "edges": [
            {
                "edge_id": "temporal-review",
                "source_node_id": "temporal",
                "source_port_id": "tracks",
                "target_node_id": "review",
                "target_port_id": "tracks",
            },
            {
                "edge_id": "review-behavior",
                "source_node_id": "review",
                "source_port_id": "poses",
                "target_node_id": "behavior",
                "target_port_id": "poses",
            },
        ],
    }

    response = client.post(
        (f"/api/v1/projects/{project['id']}/workflow-graphs/validate"),
        json=graph,
    )

    assert response.status_code == 200, response.text

    issues = response.json()["issues"]

    assert not any(item["code"] == "incompatible_port_types" for item in issues)

    assert any(
        item["code"] == "required_input_missing" and item["node_id"] == "temporal"
        for item in issues
    )
