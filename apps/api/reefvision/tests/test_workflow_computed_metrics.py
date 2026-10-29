import csv
import io
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import ComputedMetricResult, WorkflowNodeRun
from reefvision.domain.errors import ConflictError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.computed_metrics import ComputedMetricService
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_computed_metrics import (
    add_records,
    create_density_definition,
    scientific_record,
)


def metric_graph(definition_id: str, organisms_id: str, area_id: str) -> dict[str, object]:
    return {
        "graph_id": "computed-density",
        "name": "Computed organism density",
        "schema_version": "workflow-graph-0001",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "records",
                "node_type": "scientific_records_source",
                "parameters": {"record_ids": [organisms_id, area_id]},
            },
            {
                "node_id": "metric",
                "node_type": "computed_metric",
                "parameters": {
                    "definition_id": definition_id,
                    "bindings": {"organisms": organisms_id, "surveyed_area": area_id},
                },
            },
        ],
        "edges": [
            {
                "edge_id": "project-records",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "records",
                "target_port_id": "project",
            },
            {
                "edge_id": "records-metric",
                "source_node_id": "records",
                "source_port_id": "records",
                "target_node_id": "metric",
                "target_port_id": "records",
            },
        ],
    }


def save_and_queue(client: TestClient, project_id: str, graph: dict[str, object]) -> dict:
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
    return queued.json()


def test_saved_workflow_executes_and_reloads_persisted_metric_result(client: TestClient) -> None:
    project = create_project(client, "Metric workflow")
    organisms, area = add_records(
        client,
        project["id"],
        [
            scientific_record("organism_count", 12, "count"),
            scientific_record("surveyed_area", 2, "m2"),
        ],
    )
    definition = create_density_definition(client, project["id"])
    graph = metric_graph(definition["id"], organisms["id"], area["id"])

    registry = client.get("/api/v1/workflow-graphs/node-registry")
    registry_by_type = {item["node_type"]: item for item in registry.json()}
    assert registry_by_type["scientific_records_source"]["executable"] is True
    assert registry_by_type["computed_metric"]["input_ports"][0]["accepted_types"] == [
        "scientific_record_collection"
    ]
    plan = client.post(f"/api/v1/projects/{project['id']}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True

    run = save_and_queue(client, project["id"], graph)
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run["job_id"])
    )

    detail = client.get(f"/api/v1/workflow-runs/{run['id']}")
    assert detail.status_code == 200, detail.text
    payload = detail.json()
    assert payload["run"]["status"] == "succeeded"
    artifact = next(
        item for item in payload["artifacts"] if item["data_type"] == "computed_metric_result"
    )
    assert artifact["payload_json"]["value"] == pytest.approx(6)
    assert artifact["payload_json"]["unit"] == "count/m2"
    assert len(artifact["payload_sha256"]) == 64
    results = client.get(f"/api/v1/projects/{project['id']}/computed-metric-results").json()
    assert results["total"] == 1
    assert results["items"][0]["id"] == artifact["payload_json"]["result_id"]
    assert results["items"][0]["workflow_run_id"] == run["id"]
    metric_node = next(node for node in payload["nodes"] if node["node_type"] == "computed_metric")
    assert results["items"][0]["workflow_node_run_id"] == metric_node["id"]
    exported = client.get(f"/api/v1/projects/{project['id']}/computed-metric-results.csv")
    csv_row = next(csv.DictReader(io.StringIO(exported.text)))
    assert csv_row["workflow_run_id"] == run["id"]
    assert csv_row["workflow_node_run_id"] == metric_node["id"]

    with app.state.session_factory() as session:
        replay = ComputedMetricService(session).calculate(
            project["id"],
            definition["id"],
            {"organisms": organisms["id"], "surveyed_area": area["id"]},
            workflow_run_id=run["id"],
            workflow_node_run_id=metric_node["id"],
        )
        assert replay.id == results["items"][0]["id"]
        with pytest.raises(ConflictError, match="conflicts"):
            ComputedMetricService(session).calculate(
                project["id"],
                definition["id"],
                {"organisms": area["id"], "surveyed_area": organisms["id"]},
                workflow_run_id=run["id"],
                workflow_node_run_id=metric_node["id"],
            )


@pytest.mark.parametrize(
    "failure", ["missing_record", "outside_source", "duplicate_binding", "qc_rejected"]
)
def test_workflow_metric_failure_is_persisted_without_result(
    client: TestClient, failure: str
) -> None:
    project = create_project(client, f"Metric workflow {failure}")
    organisms, area = add_records(
        client,
        project["id"],
        [
            scientific_record(
                "organism_count",
                12,
                "count",
                qc="rejected" if failure == "qc_rejected" else "unassessed",
            ),
            scientific_record("surveyed_area", 2, "m2"),
        ],
    )
    definition = create_density_definition(client, project["id"])
    graph = metric_graph(definition["id"], organisms["id"], area["id"])
    nodes = cast(list[dict], graph["nodes"])
    if failure == "missing_record":
        nodes[1]["parameters"] = {"record_ids": [str(uuid4()), area["id"]]}
    elif failure == "outside_source":
        nodes[1]["parameters"] = {"record_ids": [organisms["id"]]}
    elif failure == "duplicate_binding":
        nodes[2]["parameters"]["bindings"] = {
            "organisms": organisms["id"],
            "surveyed_area": organisms["id"],
        }

    run = save_and_queue(client, project["id"], graph)
    app = cast(FastAPI, client.app)
    assert not process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{run['id']}").json()
    assert detail["run"]["status"] == "failed"
    assert (
        client.get(f"/api/v1/projects/{project['id']}/computed-metric-results").json()["total"] == 0
    )
    with app.state.session_factory() as session:
        assert (
            session.scalar(
                select(ComputedMetricResult).where(ComputedMetricResult.project_id == project["id"])
            )
            is None
        )
        failed_node = session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run["id"],
                WorkflowNodeRun.status == "failed",
            )
        )
        assert failed_node is not None
        if failure == "duplicate_binding":
            assert "distinct scientific record" in (failed_node.error_message or "")
        if failure == "qc_rejected":
            assert "suspect or rejected" in (failed_node.error_message or "")
