"""QC scoring weights agree between standalone and executable saved workflows."""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import WorkflowArtifact, WorkflowNodeRun
from reefvision.domain.errors import ValidationError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.review_queues import ReviewScoreWeights
from reefvision.services.workflow_review_queue import create_review_queue_workflow_artifact
from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_workflow_review_queue_16 import _graph


def _weighted_graph(weights: dict[str, float] | None) -> dict[str, Any]:
    graph = _graph()
    graph["nodes"] = [
        {"node_id": "project", "node_type": "project_source"},
        {
            "node_id": "qc",
            "node_type": "qc_review_queue",
            "parameters": {"signal_weights": weights},
        },
    ]
    return graph


def _execute(client: TestClient, project_id: str, graph: dict[str, Any]) -> dict[str, Any]:
    saved = client.post(f"/api/v1/projects/{project_id}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    queued = client.post(
        f"/api/v1/projects/{project_id}/workflow-runs",
        json={"graph_record_id": saved.json()["id"]},
    )
    assert queued.status_code == 202, queued.text
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(queued.json()["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    return detail.json()


def _payload(detail: dict[str, Any]) -> dict[str, Any]:
    matches = [
        item["payload_json"]
        for item in detail["artifacts"]
        if item["data_type"] == "review_queue_reference"
    ]
    assert len(matches) == 1
    return matches[0]


def test_saved_custom_weights_match_standalone_scoring(client: TestClient) -> None:
    project = create_project(client, "Researcher-weighted coral QC")
    project_id = project["id"]
    assert len(import_one(client, project_id, filename="weighted-coral.png")["successful"]) == 1
    weights = {name: 0.0 for name in ReviewScoreWeights.model_fields}
    weights["unreviewed_state"] = 1.0
    standalone = client.post(
        f"/api/v1/projects/{project_id}/review-queues", json={"signal_weights": weights}
    )
    assert standalone.status_code == 201, standalone.text
    graph = _weighted_graph(weights)
    plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["valid"] and plan.json()["executable"]
    payload = _payload(_execute(client, project_id, graph))
    assert payload["priority_score_unit"] == "dimensionless"
    assert payload["review_status"] == "requires_researcher_review"
    workflow = client.get(f"/api/v1/review-queues/{payload['queue_id']}")
    assert workflow.status_code == 200, workflow.text
    assert workflow.json()["configuration_json"]["weights"] == weights
    standalone_items = client.get(f"/api/v1/review-queues/{standalone.json()['id']}/items").json()[
        "items"
    ]
    workflow_items = client.get(f"/api/v1/review-queues/{payload['queue_id']}/items").json()[
        "items"
    ]
    assert len(standalone_items) == len(workflow_items) == 1
    assert standalone_items[0]["score"] == workflow_items[0]["score"]
    assert standalone_items[0]["input_checksum"] == workflow_items[0]["input_checksum"]
    assert workflow_items[0]["review_state"] == "pending"


@pytest.mark.parametrize(
    "weights",
    [
        {name: 0.0 for name in ReviewScoreWeights.model_fields},
        {"not_a_qc_signal": 1.0},
        {"unreviewed_state": -1.0},
        {"low_mean_confidence": 1e308, "low_min_confidence": 1e308},
    ],
)
def test_invalid_weights_fail_saved_graph_planning(
    client: TestClient, weights: dict[str, float]
) -> None:
    project_id = create_project(client, "Invalid workflow QC weights")["id"]
    plan = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs/plan",
        json=_weighted_graph(weights),
    )
    assert plan.status_code == 200, plan.text
    assert not plan.json()["valid"] and not plan.json()["executable"]
    assert any(issue["code"] == "invalid_qc_signal_weights" for issue in plan.json()["issues"])
    queues = client.get(f"/api/v1/projects/{project_id}/review-queues")
    assert queues.status_code == 200, queues.text
    assert queues.json() == []


@pytest.mark.parametrize("legacy", [True, False])
def test_saved_qc_retry_preserves_original_weights_and_legacy_defaults(
    client: TestClient, legacy: bool
) -> None:
    project_id = create_project(client, "QC weight retry integrity")["id"]
    assert len(import_one(client, project_id, filename="retry-weight.png")["successful"]) == 1
    weights = None
    if not legacy:
        weights = {name: 0.0 for name in ReviewScoreWeights.model_fields}
        weights["unreviewed_state"] = 1.0
    payload = _payload(_execute(client, project_id, _weighted_graph(weights)))
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        nodes = session.scalars(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == payload["workflow_run_id"]
            )
        ).all()
        node = next(item for item in nodes if item.node_type == "qc_review_queue")
        source = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.workflow_run_id == payload["workflow_run_id"],
                WorkflowArtifact.producer_port_id == "project",
            )
        )
        assert source is not None
        if legacy:
            node.parameters_json = {
                key: value for key, value in node.parameters_json.items() if key != "signal_weights"
            }
        else:
            node.parameters_json = {**node.parameters_json, "signal_weights": None}
        session.flush()
        parameters = {
            **node.parameters_json,
            "signal_weights": None,
            "__workflow_run_id": payload["workflow_run_id"],
            "__workflow_node_run_id": node.id,
        }
        if legacy:
            output = create_review_queue_workflow_artifact(
                session, app.state.settings, project_id, parameters, {"project": [source]}
            )
            assert output[0]["payload"] == payload
        else:
            with pytest.raises(ValidationError, match="parameters changed or queue incomplete"):
                create_review_queue_workflow_artifact(
                    session, app.state.settings, project_id, parameters, {"project": [source]}
                )
        session.rollback()
    items = client.get(f"/api/v1/review-queues/{payload['queue_id']}/items")
    assert items.status_code == 200, items.text
    assert items.json()["items"][0]["review_state"] == "pending"
