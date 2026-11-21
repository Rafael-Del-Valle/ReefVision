from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from reefvision.tests.test_workflow_pose_training_phase10 import _frozen_dataset


def test_plans_explicit_pose_dataset_and_video_pins(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, frozen = _frozen_dataset(client, monkeypatch)
    project_id = project["id"]
    video = client.get(f"/api/v1/projects/{project_id}/videos").json()[0]
    dataset = {
        "node_id": "dataset",
        "node_type": "pose_training_dataset",
        "parameters": {"dataset_id": frozen["id"], "manifest_sha256": frozen["manifest_sha256"]},
    }
    recording = {
        "node_id": "recording",
        "node_type": "project_video_source",
        "parameters": {"video_id": video["id"], "video_sha256": video["sha256"]},
    }
    graph = {
        "graph_id": "frozen-source-pins",
        "name": "Frozen source pins",
        "nodes": [{"node_id": "project", "node_type": "project_source"}, dataset, recording],
        "edges": [
            {
                "edge_id": "project-recording",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "recording",
                "target_port_id": "project",
            }
        ],
    }
    path = f"/api/v1/projects/{project_id}/workflow-graphs"
    assert client.post(f"{path}/plan", json=graph).json()["executable"]
    for source, field, expected_code in (
        (dataset, "manifest_sha256", "invalid_pose_dataset_source"),
        (recording, "video_sha256", "video_source_stale"),
    ):
        parameters = source["parameters"]
        assert isinstance(parameters, dict)
        original = parameters[field]
        parameters[field] = "0" * 64
        result = client.post(f"{path}/plan", json=graph)
        assert result.status_code == 200, result.text
        planned = result.json()
        assert planned["executable"] is False, planned
        assert any(
            issue["node_id"] == source["node_id"] and issue["code"] == expected_code
            for issue in planned["issues"]
        )
        parameters[field] = original

    # Older persisted graphs carry IDs without pins.
    dataset["parameters"] = {"dataset_id": frozen["id"]}
    recording["parameters"] = {"video_id": video["id"]}
    assert client.post(f"{path}/plan", json=graph).json()["executable"]
