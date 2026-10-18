"""ReefVision 1.6 QC queue workflow and standalone API regression."""

from __future__ import annotations

from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import WorkflowArtifact
from reefvision.domain.errors import ValidationError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.workflow_runtime_adapters import execute_runtime_adapter
from reefvision.tests.test_annotations import create_project, import_one


def _graph() -> dict[str, object]:
    return {
        "graph_id": "qc-review-queue-16",
        "name": "QC review queue",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "qc", "node_type": "qc_review_queue"},
        ],
        "edges": [
            {
                "edge_id": "project-qc",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "qc",
                "target_port_id": "project",
            }
        ],
    }


def test_qc_queue_standalone_and_saved_workflow_share_service(client: TestClient) -> None:
    project = create_project(client, "QC review workflow")
    imported = import_one(
        client,
        project["id"],
        filename="qc-review-workflow.png",
        relative_path="qc-review/workflow.png",
    )
    assert len(imported["successful"]) == 1

    standalone = client.post(f"/api/v1/projects/{project['id']}/review-queues", json={})
    assert standalone.status_code == 201, standalone.text
    assert standalone.json()["item_count"] == 1

    registry = client.get("/api/v1/workflow-graphs/node-registry")
    assert registry.status_code == 200, registry.text
    node = next(x for x in registry.json() if x["node_type"] == "qc_review_queue")
    assert node["executable"] is True
    assert node["output_ports"][0]["accepted_types"] == ["review_queue_reference"]

    plan = client.post(f"/api/v1/projects/{project['id']}/workflow-graphs/plan", json=_graph())
    assert plan.status_code == 200, plan.text
    assert plan.json()["valid"] and plan.json()["executable"]

    saved = client.post(
        f"/api/v1/projects/{project['id']}/workflow-graphs",
        json={"graph": _graph()},
    )
    assert saved.status_code == 201, saved.text
    queued = client.post(
        f"/api/v1/projects/{project['id']}/workflow-runs",
        json={"graph_record_id": saved.json()["id"]},
    )
    assert queued.status_code == 202, queued.text
    run = queued.json()
    app = cast(FastAPI, client.app)
    assert (
        process_workflow_run_job(
            app.state.settings,
            app.state.session_factory,
            str(run["job_id"]),
        )
        is True
    )

    detail = client.get(f"/api/v1/workflow-runs/{run['id']}")
    assert detail.status_code == 200, detail.text
    payload = detail.json()
    assert payload["run"]["status"] == "succeeded"
    outputs = [
        item for item in payload["artifacts"] if item["data_type"] == "review_queue_reference"
    ]
    assert len(outputs) == 1
    result = outputs[0]["payload_json"]
    assert result["item_count"] == 1
    assert result["priority_score_unit"] == "dimensionless"
    assert result["review_status"] == "requires_researcher_review"
    assert result["workflow_run_id"] == run["id"]
    assert len(outputs[0]["payload_sha256"]) == 64
    response = client.get(f"/api/v1/review-queues/{result['queue_id']}")
    assert response.status_code == 200, response.text
    assert response.json()["created_by"].startswith("workflow:")

    item_id = client.get(
        f"/api/v1/review-queues/{result['queue_id']}/items"
    ).json()["items"][0]["id"]
    event_url = f"/api/v1/review-queues/{result['queue_id']}/items/{item_id}/events"
    comment = client.post(
        event_url,
        json={
            "client_request_id": str(uuid4()),
            "event_type": "comment",
            "actor": "researcher",
            "comment": "Review this saved workflow image",
        },
    )
    assert comment.status_code == 201, comment.text
    assert client.get(event_url).json()["total"] == 1

    with app.state.session_factory() as session:
        source = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.workflow_run_id == run["id"],
                WorkflowArtifact.data_type == "project_reference",
            )
        )
        assert source is not None
        qc_node = next(item for item in payload["nodes"] if item["node_id"] == "qc")
        params = {
            "__workflow_run_id": run["id"],
            "__workflow_node_run_id": qc_node["id"],
        }
        retry = execute_runtime_adapter(
            "qc_review_queue",
            session=session,
            settings=app.state.settings,
            project_id=project["id"],
            parameters=params,
            inputs={"project": [source]},
        )
        assert retry[0]["payload"]["queue_id"] == result["queue_id"]
        with pytest.raises(ValidationError, match="retry parameters changed"):
            execute_runtime_adapter(
                "qc_review_queue",
                session=session,
                settings=app.state.settings,
                project_id=project["id"],
                parameters={**params, "review_below_confidence": 0.5},
                inputs={"project": [source]},
            )
        with pytest.raises(ValidationError, match="foreign project"):
            execute_runtime_adapter(
                "qc_review_queue",
                session=session,
                settings=app.state.settings,
                project_id="not-the-project",
                parameters=params,
                inputs={"project": [source]},
            )

    listing = client.get(f"/api/v1/projects/{project['id']}/review-queues")
    assert listing.status_code == 200, listing.text
    assert len(listing.json()) == 2
