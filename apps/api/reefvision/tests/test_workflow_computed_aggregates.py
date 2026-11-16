from __future__ import annotations

from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import WorkflowNodeRun
from reefvision.domain.errors import ConflictError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.computed_aggregate_metrics import ComputedAggregateMetricService
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_computed_aggregate_metrics import (
    _calculate,
    _definition,
    _import,
    _save,
)
from reefvision.tests.test_workflow_computed_metrics import save_and_queue


def aggregate_graph(definition_id: str, image_ids: list[str]) -> dict[str, object]:
    return {
        "graph_id": "reviewed-annotation-aggregate",
        "name": "Reviewed annotation aggregate",
        "schema_version": "workflow-graph-0001",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "aggregate",
                "node_type": "annotation_aggregate",
                "parameters": {"definition_id": definition_id, "image_ids": image_ids},
            },
        ],
        "edges": [
            {
                "edge_id": "project-aggregate",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "aggregate",
                "target_port_id": "project",
            }
        ],
    }


def _run(client: TestClient, project_id: str, graph: dict[str, object]) -> tuple[dict, dict]:
    queued = save_and_queue(client, project_id, graph)
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(queued["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{queued['id']}")
    assert detail.status_code == 200, detail.text
    return queued, detail.json()


def test_workflow_aggregate_matches_standalone_and_persists_lineage(client: TestClient) -> None:
    project = create_project(client, "Aggregate workflow")
    first = _import(client, project["id"], 21)
    second = _import(client, project["id"], 22)
    label = str(project["label_classes"][0]["id"])
    _save(client, first, [label, label])
    _save(client, second, [label])
    for image_id in (first, second):
        response = client.patch(
            f"/api/v1/images/{image_id}",
            json={"annotation_status": "reviewed", "group_key": "colony-a"},
        )
        assert response.status_code == 200, response.text
    definition = _definition(client, project["id"], grouping_level="image_group_key")
    standalone = _calculate(client, project["id"], definition["id"], [first, second]).json()
    graph = aggregate_graph(definition["id"], [first, second])

    registry = client.get("/api/v1/workflow-graphs/node-registry").json()
    node = next(item for item in registry if item["node_type"] == "annotation_aggregate")
    assert node["input_ports"][0]["accepted_types"] == ["project_reference"]
    assert node["output_ports"][0]["accepted_types"] == ["computed_metric_result"]
    plan = client.post(f"/api/v1/projects/{project['id']}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True

    run, detail = _run(client, project["id"], graph)
    artifact = next(
        item for item in detail["artifacts"] if item["data_type"] == "computed_metric_result"
    )
    results = client.get(f"/api/v1/projects/{project['id']}/computed-aggregate-results").json()[
        "items"
    ]
    workflow_result = next(
        item for item in results if item["id"] == artifact["payload_json"]["result_id"]
    )
    assert workflow_result["observation_count"] == standalone["observation_count"] == 3
    assert workflow_result["groups"] == standalone["groups"]
    assert workflow_result["mean_per_independent_unit"] == standalone["mean_per_independent_unit"]
    assert workflow_result["content_sha256"] == standalone["content_sha256"]
    assert artifact["payload_json"]["content_sha256"] == workflow_result["content_sha256"]
    assert artifact["payload_sha256"] != workflow_result["content_sha256"]
    assert workflow_result["workflow_run_id"] == run["id"]
    aggregate_node = next(
        item for item in detail["nodes"] if item["node_type"] == "annotation_aggregate"
    )
    assert workflow_result["workflow_node_run_id"] == aggregate_node["id"]

    second_run, second_detail = _run(client, project["id"], graph)
    second_artifact = next(
        item for item in second_detail["artifacts"] if item["data_type"] == "computed_metric_result"
    )
    second_result = next(
        item
        for item in client.get(
            f"/api/v1/projects/{project['id']}/computed-aggregate-results"
        ).json()["items"]
        if item["id"] == second_artifact["payload_json"]["result_id"]
    )
    assert second_run["id"] != run["id"]
    assert second_result["content_sha256"] == workflow_result["content_sha256"]

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        service = ComputedAggregateMetricService(session)
        replay = service.calculate(
            project["id"],
            definition["id"],
            [first, second],
            workflow_run_id=run["id"],
            workflow_node_run_id=aggregate_node["id"],
        )
        assert replay.id == workflow_result["id"]
        with pytest.raises(ConflictError, match="conflicts"):
            service.calculate(
                project["id"],
                definition["id"],
                [first],
                workflow_run_id=run["id"],
                workflow_node_run_id=aggregate_node["id"],
            )


def test_workflow_aggregate_failure_persists_no_result_or_artifact(client: TestClient) -> None:
    project = create_project(client, "Aggregate workflow failure")
    image_id = _import(client, project["id"], 23)
    label = str(project["label_classes"][0]["id"])
    _save(client, image_id, [label])
    definition = _definition(client, project["id"])
    graph = aggregate_graph(definition["id"], [str(uuid4())])
    queued = save_and_queue(client, project["id"], graph)
    app = cast(FastAPI, client.app)
    assert not process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(queued["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{queued['id']}").json()
    assert detail["run"]["status"] == "failed"
    assert not any(item["data_type"] == "computed_metric_result" for item in detail["artifacts"])
    assert (
        client.get(f"/api/v1/projects/{project['id']}/computed-aggregate-results").json()["total"]
        == 0
    )
    with app.state.session_factory() as session:
        failed = (
            session.query(WorkflowNodeRun)
            .filter_by(workflow_run_id=queued["id"], status="failed")
            .one()
        )
        assert "belong to this project" in (failed.error_message or "")
