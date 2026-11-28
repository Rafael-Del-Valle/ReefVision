from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.jobs.project_exchange import process_project_exchange_export_job
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.ml.providers import DetectionPrediction, DetectionSettings
from reefvision.services.models import ModelService
from reefvision.tests.test_image_adjustments_v18 import make_source, save_recipe
from reefvision.tests.test_model_inference import (
    FakeDetectorRegistrationProvider,
    approve_generated_checkpoint,
    register_model,
)
from reefvision.tests.test_scientific_project_exchange import import_archive


def test_saved_adjustment_replays_two_identical_typed_artifacts_and_rejects_wrong_pin(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, image_id, original = make_source(client)
    saved = save_recipe(client, image_id, original)
    receipt = saved["receipt"]
    worker_inputs: list[str] = []

    class InspectingDetector(FakeDetectorRegistrationProvider):
        def predict(
            self, image_path: Path, settings: DetectionSettings
        ) -> list[DetectionPrediction]:
            worker_inputs.append(sha256(image_path.read_bytes()).hexdigest())
            return []

    monkeypatch.setattr(ModelService, "_provider_for_purpose", lambda *_: InspectingDetector())
    monkeypatch.setattr(
        "reefvision.jobs.inference.detection_provider_for_name", lambda _: InspectingDetector()
    )
    model = register_model(
        client,
        project["id"],
        purpose="detector",
        filename="graph.pt",
        display_name="Graph detector",
    )
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
            {
                "node_id": "model",
                "node_type": "registered_model_source",
                "parameters": {"model_id": model["id"]},
            },
            {"node_id": "infer", "node_type": "detection_inference"},
        ],
        "edges": [
            {
                "edge_id": "project-binding",
                "source_node_id": "source",
                "source_port_id": "project",
                "target_node_id": "correction",
                "target_port_id": "project",
            },
            {
                "edge_id": "catalog",
                "source_node_id": "source",
                "source_port_id": "project",
                "target_node_id": "model",
                "target_port_id": "project",
            },
            {
                "edge_id": "input",
                "source_node_id": "correction",
                "source_port_id": "images",
                "target_node_id": "infer",
                "target_port_id": "images",
            },
            {
                "edge_id": "checkpoint",
                "source_node_id": "model",
                "source_port_id": "model",
                "target_node_id": "infer",
                "target_port_id": "model",
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

    def replay(record_id: str, project_base: str = base) -> dict[str, Any]:
        queued = client.post(project_base + "/workflow-runs", json={"graph_record_id": record_id})
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
    assert worker_inputs == [receipt["rendition_sha256"]] * 2
    pin["content_sha256"] = "0" * 64
    failed = replay(save_graph())
    assert failed["run"]["status"] == "failed"
    assert not any(row["data_type"] == "adjusted_image_reference" for row in failed["artifacts"])
    assert len(worker_inputs) == 2

    image = image_id
    recipe = saved["id"]
    model_id = model["id"]
    project_base = base
    for _ in range(2):
        package = client.post(
            project_base + "/exchange-packages",
            json={"include_media": True, "include_model_weights": True},
        ).json()
        assert process_project_exchange_export_job(
            test_settings, app.state.session_factory, package["job_id"]
        )
        download = client.get("/api/v1/exchange-packages/" + package["package"]["id"] + "/download")
        assert download.status_code == 200
        imported = import_archive(client, download.content)
        assert imported.status_code == 201, imported.text
        copy = imported.json()
        project_base = "/api/v1/projects/" + copy["project_id"]
        mapping = copy["package"]["options_json"]["id_map"]
        image, recipe, graph_id = mapping[image], mapping[recipe], mapping[graph_id]
        model_id = mapping[model_id]
        approve_generated_checkpoint(client, copy["project_id"], model_id, model["sha256"])
        assert client.get(f"/api/v1/images/{image}/content").content == original
        record = client.get(f"/api/v1/images/{image}/adjustments/{recipe}").json()
        assert record["receipt"] == receipt and record["content_sha256"] == saved["content_sha256"]
        rerun = replay(graph_id, project_base)
        assert rerun["run"]["status"] == "succeeded", rerun
        [reference] = [
            a for a in rerun["artifacts"] if a["data_type"] == "adjusted_image_reference"
        ]
        assert reference["payload_json"]["receipt"] == receipt
        assert reference["payload_json"]["image_ids"] == [image]
    assert worker_inputs == [receipt["rendition_sha256"]] * 4
