from __future__ import annotations

from typing import cast
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_computed_mask_coverage import (
    _definition,
    _image,
    _polygon,
    _save_masks,
)
from reefvision.tests.test_workflow_computed_metrics import save_and_queue


def mask_coverage_graph(definition_id: str, image_ids: list[str]) -> dict[str, object]:
    return {
        "graph_id": "verified-mask-coverage",
        "name": "Verified mask coverage",
        "schema_version": "workflow-graph-0001",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "coverage",
                "node_type": "mask_coverage",
                "parameters": {"definition_id": definition_id, "image_ids": image_ids},
            },
        ],
        "edges": [
            {
                "edge_id": "project-coverage",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "coverage",
                "target_port_id": "project",
            }
        ],
    }


def test_workflow_mask_coverage_matches_standalone_and_persists_lineage(
    client: TestClient,
) -> None:
    project = create_project(client, "Mask coverage workflow")
    target = str(project["label_classes"][0]["id"])
    image_id = _image(client, project["id"], index=31)
    _save_masks(
        client,
        image_id,
        [
            _polygon(str(uuid4()), target, [(1, 1), (4, 1), (4, 4), (1, 4)]),
            _polygon(str(uuid4()), target, [(3, 1), (6, 1), (6, 4), (3, 4)]),
        ],
    )
    definition = _definition(client, project["id"], target)
    graph = mask_coverage_graph(definition["id"], [image_id])

    registry = client.get("/api/v1/workflow-graphs/node-registry").json()
    node = next(item for item in registry if item["node_type"] == "mask_coverage")
    assert node["output_ports"][0]["accepted_types"] == ["computed_metric_result"]
    plan = client.post(f"/api/v1/projects/{project['id']}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True

    queued = save_and_queue(client, project["id"], graph)
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(queued["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{queued['id']}").json()
    artifact = next(
        item for item in detail["artifacts"] if item["data_type"] == "computed_metric_result"
    )
    result = client.get(f"/api/v1/projects/{project['id']}/computed-mask-coverage-results").json()[
        "items"
    ][0]
    assert result["union_area_pixels"] == 24
    assert result["workflow_run_id"] == queued["id"]
    assert artifact["payload_json"]["result_id"] == result["id"]
    assert artifact["payload_json"]["density_object_count"] == 2
    assert artifact["payload_json"]["evidence_sha256"] == result["evidence_sha256"]
