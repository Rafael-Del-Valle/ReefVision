"""Reopen and replay an immutable pose dataset through two ordinary project exchanges."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.services.project_exchange_workflows import _restore_parameters
from reefvision.tests.test_project_exchange_reefpose_workflow import _execute
from reefvision.tests.test_scientific_project_exchange import export_archive, import_archive
from reefvision.tests.test_workflow_pose_training_phase10 import _frozen_dataset


def test_exchange_preserves_a_pin_from_a_different_pose_dataset() -> None:
    source, restored = "a" * 64, "b" * 64
    stale = {"dataset_id": "other", "manifest_sha256": source}
    assert (
        _restore_parameters(
            "pose_training_dataset", stale, {source: restored}, {("expected", source): restored}
        )
        == stale
    )


def test_frozen_pose_graph_rebinds_the_pinned_dataset_at_each_exchange(
    client: TestClient, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, dataset = _frozen_dataset(client, monkeypatch)
    project_id = str(project["id"])
    dataset_id = str(dataset["id"])
    graph: dict[str, Any] = {
        "graph_id": "frozen-pose-study",
        "name": "Frozen pose study",
        "nodes": [
            {
                "node_id": "pinned",
                "node_type": "pose_training_dataset",
                "parameters": {
                    "dataset_id": dataset_id,
                    "manifest_sha256": dataset["manifest_sha256"],
                },
            },
            {
                "node_id": "historical",
                "node_type": "pose_training_dataset",
                "parameters": {"dataset_id": dataset_id},
            },
        ],
        "edges": [],
    }
    response = client.post(f"/api/v1/projects/{project_id}/workflow-graphs", json={"graph": graph})
    assert response.status_code == 201, response.text
    graph_id = response.json()["id"]
    run = _execute(client, project_id, graph_id)["run"]
    assert run["status"] == "succeeded", run["error_message"]
    for _ in range(2):
        previous_sha = client.get(f"/api/v1/pose-training-datasets/{dataset_id}").json()[
            "manifest_sha256"
        ]
        archive = export_archive(client, test_settings, project_id)
        imported = import_archive(client, archive)
        assert imported.status_code == 201, imported.text
        transfer = imported.json()
        mapping = transfer["package"]["options_json"]["id_map"]
        project_id, dataset_id, graph_id = (
            transfer["project_id"],
            mapping[dataset_id],
            mapping[graph_id],
        )
        frozen = client.get(f"/api/v1/pose-training-datasets/{dataset_id}").json()
        assert frozen["manifest_sha256"] != previous_sha
        graphs = client.get(f"/api/v1/projects/{project_id}/workflow-graphs").json()
        saved = next(record for record in graphs if record["id"] == graph_id)
        inputs = {n["node_id"]: n["parameters"] for n in saved["graph_json"]["nodes"]}
        assert inputs["pinned"] == {
            "dataset_id": dataset_id,
            "manifest_sha256": frozen["manifest_sha256"],
        }
        assert inputs["historical"] == {"dataset_id": dataset_id}
        prior = client.get(f"/api/v1/workflow-runs/{mapping[run['id']]}").json()
        assert prior["run"]["graph_sha256"] == saved["graph_sha256"]
        for artifact in prior["artifacts"]:
            assert artifact["payload_json"]["manifest_sha256"] == frozen["manifest_sha256"]
        run = _execute(client, project_id, graph_id)["run"]
        assert run["status"] == "succeeded", run["error_message"]
