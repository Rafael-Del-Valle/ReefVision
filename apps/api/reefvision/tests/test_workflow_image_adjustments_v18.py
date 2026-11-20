from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_image_adjustments_v18 import make_source, save_recipe


def test_saved_adjustment_replays_two_identical_typed_artifacts_and_rejects_wrong_pin(
    client: TestClient, test_settings: Settings
) -> None:
    project, image_id, original = make_source(client)
    saved = save_recipe(client, image_id, original)
    receipt = saved["receipt"]
    pin = {
        "image_id": image_id,
        "recipe_id": saved["id"],
        "content_sha256": saved["content_sha256"],
        "original_sha256": receipt["original_sha256"],
        "rendition_sha256": receipt["rendition_sha256"],
    }
    graph = {
        "graph_id": "rgb-recipe-proof",
        "name": "Saved raw-grid correction",
        "nodes": [
            {"node_id": "source", "node_type": "project_source"},
            {"node_id": "correction", "node_type": "underwater_adjustment", "parameters": pin},
        ],
        "edges": [
            {
                "edge_id": "project-binding",
                "source_node_id": "source",
                "source_port_id": "project",
                "target_node_id": "correction",
                "target_port_id": "project",
            },
        ],
    }
    base = f"/api/v1/projects/{project['id']}"

    def save_graph() -> str:
        response = client.post(base + "/workflow-graphs", json={"graph": graph})
        assert response.status_code == 201, response.text
        return response.json()["id"]

    graph_id = save_graph()
    app = cast(FastAPI, client.app)

    def replay(record_id: str) -> dict[str, Any]:
        queued = client.post(base + "/workflow-runs", json={"graph_record_id": record_id})
        assert queued.status_code == 202, queued.text
        run = queued.json()
        process_workflow_run_job(test_settings, app.state.session_factory, run["job_id"])
        return client.get("/api/v1/workflow-runs/" + run["id"]).json()

    first, second = replay(graph_id), replay(graph_id)
    assert first["run"]["id"] != second["run"]["id"]
    assert first["run"]["status"] == second["run"]["status"] == "succeeded"
    first_output, second_output = (
        next(row for row in run["artifacts"] if row["data_type"] == "adjusted_image_reference")
        for run in (first, second)
    )
    assert first_output["payload_sha256"] == second_output["payload_sha256"]
    assert first_output["payload_json"]["receipt"] == receipt
    assert first_output["payload_json"]["image_ids"] == [image_id]
    pin["content_sha256"] = "0" * 64
    failed = replay(save_graph())
    assert failed["run"]["status"] == "failed"
    assert not any(row["data_type"] == "adjusted_image_reference" for row in failed["artifacts"])
