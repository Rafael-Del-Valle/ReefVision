"""Exercise saved longitudinal ecology graphs, provenance and unverified-data boundaries."""

from __future__ import annotations

from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project


def _observations() -> list[dict[str, object]]:
    return [
        {
            "organism_id": "coral-1",
            "metric_name": "polyp_count",
            "source_record_id": "day0",
            "observed_at": "2026-04-01T12:00:00Z",
            "value": 10,
            "unit": "count",
        },
        {
            "organism_id": "coral-1",
            "metric_name": "polyp_count",
            "source_record_id": "day1",
            "observed_at": "2026-04-02T12:00:00Z",
            "value": 12,
            "unit": "count",
        },
    ]


def _graph(observations: list[dict[str, object]]) -> dict[str, Any]:
    return {
        "graph_id": "ecology-longitudinal-1-2",
        "name": "Exploratory ecology workflow",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "ecology",
                "node_type": "ecology_longitudinal_analysis",
                "parameters": {"observations": observations},
            },
        ],
        "edges": [
            {
                "edge_id": "project-ecology",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "ecology",
                "target_port_id": "project",
            }
        ],
    }


def test_saved_ecology_workflow_persists_unverified_artifact(client: TestClient) -> None:
    project = create_project(client, "Ecology workflow")
    project_id = str(project["id"])
    registry_response = client.get("/api/v1/workflow-graphs/node-registry")
    assert registry_response.status_code == 200
    nodes = {item["node_type"]: item for item in registry_response.json()}
    ecology = nodes["ecology_longitudinal_analysis"]
    assert ecology["executable"] is True
    assert ecology["input_ports"][0]["accepted_types"] == ["project_reference"]
    assert ecology["output_ports"][0]["accepted_types"] == ["longitudinal_analysis"]

    graph = _graph(_observations())
    plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    saved = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs",
        json={"graph": graph, "create_new_revision": True},
    )
    assert saved.status_code == 201, saved.text
    queue = client.post(
        f"/api/v1/projects/{project_id}/workflow-runs",
        json={"graph_record_id": saved.json()["id"]},
    )
    assert queue.status_code == 202, queue.text
    app = cast(FastAPI, client.app)
    assert (
        process_workflow_run_job(
            app.state.settings,
            app.state.session_factory,
            str(queue.json()["job_id"]),
        )
        is True
    )
    detail = client.get(f"/api/v1/workflow-runs/{queue.json()['id']}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["run"]["status"] == "succeeded"
    analyses = [item for item in body["artifacts"] if item["data_type"] == "longitudinal_analysis"]
    assert len(analyses) == 1
    payload = analyses[0]["payload_json"]
    assert payload["project_id"] == project_id
    assert payload["evidence_level"] == "caller_supplied_unverified"
    assert payload["source_record_ids"] == ["day0", "day1"]
    assert payload["changes"][0]["absolute_change"] == 2
    standalone = client.post(
        "/api/v1/ecology/longitudinal-analysis",
        json={"observations": _observations()},
    )
    assert standalone.status_code == 200, standalone.text
    assert payload["analysis_provenance"] == standalone.json()["analysis_provenance"]


def test_unverified_ecology_cannot_enter_verified_dataset(client: TestClient) -> None:
    project = create_project(client, "Ecology verified-boundary")
    graph = _graph(_observations())
    graph["nodes"].append({"node_id": "dataset", "node_type": "dataset_version_create"})
    graph["edges"].append(
        {
            "edge_id": "unverified-into-reviewed",
            "source_node_id": "ecology",
            "source_port_id": "analysis",
            "target_node_id": "dataset",
            "target_port_id": "reviewed",
        }
    )
    response = client.post(f"/api/v1/projects/{project['id']}/workflow-graphs/validate", json=graph)
    assert response.status_code == 200, response.text
    assert response.json()["valid"] is False
    assert any(issue["code"] == "incompatible_port_types" for issue in response.json()["issues"])
