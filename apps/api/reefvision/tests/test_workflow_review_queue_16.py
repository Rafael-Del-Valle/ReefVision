"""ReefVision 1.6 QC queue workflow and standalone API regression."""

from __future__ import annotations

from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import (
    ReviewQueue,
    ReviewQueueItem,
    WorkflowArtifact,
    WorkflowNodeRun,
)
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
    assert len(standalone.json()["input_checksums_json"]["scoring_provenance_sha256"]) == 64

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
    assert len(response.json()["input_checksums_json"]["scoring_provenance_sha256"]) == 64

    item_id = client.get(f"/api/v1/review-queues/{result['queue_id']}/items").json()["items"][0][
        "id"
    ]
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
        persisted_node = session.get(WorkflowNodeRun, qc_node["id"])
        assert persisted_node is not None
        assert persisted_node.node_type == "qc_review_queue"
        saved_parameters = dict(persisted_node.parameters_json or {})
        assert "source_quality_control_run_id" in saved_parameters
        assert "review_below_confidence" in saved_parameters
        params = {
            **saved_parameters,
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
        # Persisted snapshots must fail closed on retry, not silently reuse
        # tampered scores even when workflow parameters are unchanged.
        saved_item = session.scalar(
            select(ReviewQueueItem).where(ReviewQueueItem.review_queue_id == result["queue_id"])
        )
        assert saved_item is not None
        original_score = saved_item.score
        saved_item.score = original_score + 1.0
        session.flush()
        with pytest.raises(ValidationError, match="snapshot failed integrity"):
            execute_runtime_adapter(
                "qc_review_queue",
                session=session,
                settings=app.state.settings,
                project_id=project["id"],
                parameters=params,
                inputs={"project": [source]},
            )
        saved_item.score = original_score
        session.flush()
        # The request may omit a QC run even when the service resolves one.
        # A changed stored configuration must never silently alter provenance.
        saved_queue = session.get(ReviewQueue, result["queue_id"])
        assert saved_queue is not None
        original_config = dict(saved_queue.configuration_json)
        saved_queue.configuration_json = {
            **original_config,
            "source_quality_control_run_id": "other-qc-run",
        }
        session.flush()
        with pytest.raises(ValidationError, match="snapshot failed integrity"):
            execute_runtime_adapter(
                "qc_review_queue",
                session=session,
                settings=app.state.settings,
                project_id=project["id"],
                parameters=params,
                inputs={"project": [source]},
            )
        saved_queue.configuration_json = original_config
        session.flush()
        # The saved workflow must also reject altered scoring provenance,
        # even when the original item scores and scope checksum are intact.
        original_formula_version = saved_queue.formula_version
        saved_queue.formula_version = "unverified-scoring-version"
        session.flush()
        with pytest.raises(ValidationError, match="snapshot failed integrity"):
            execute_runtime_adapter(
                "qc_review_queue",
                session=session,
                settings=app.state.settings,
                project_id=project["id"],
                parameters=params,
                inputs={"project": [source]},
            )
        saved_queue.formula_version = original_formula_version
        session.flush()
        restored = execute_runtime_adapter(
            "qc_review_queue",
            session=session,
            settings=app.state.settings,
            project_id=project["id"],
            parameters=params,
            inputs={"project": [source]},
        )
        assert restored[0]["payload"]["queue_id"] == result["queue_id"]
        # The saved scientific summary is independent of the scope checksum.
        # Reject tampering without changing reviewer decisions or live QC.
        original_summary = dict(saved_queue.summary_json)
        saved_queue.summary_json = {
            **original_summary,
            "average_score": original_summary["average_score"] + 1.0,
        }
        session.flush()
        with pytest.raises(ValidationError, match="snapshot failed integrity"):
            execute_runtime_adapter(
                "qc_review_queue",
                session=session,
                settings=app.state.settings,
                project_id=project["id"],
                parameters=params,
                inputs={"project": [source]},
            )
        saved_queue.summary_json = original_summary
        session.flush()
        restored = execute_runtime_adapter(
            "qc_review_queue",
            session=session,
            settings=app.state.settings,
            project_id=project["id"],
            parameters=params,
            inputs={"project": [source]},
        )
        assert restored[0]["payload"]["queue_id"] == result["queue_id"]
        # Omitting a persisted optional parameter is a provenance change,
        # even when its saved value was null.
        missing_source = dict(params)
        missing_source.pop("source_quality_control_run_id")
        with pytest.raises(ValidationError, match="retry parameters changed"):
            execute_runtime_adapter(
                "qc_review_queue",
                session=session,
                settings=app.state.settings,
                project_id=project["id"],
                parameters=missing_source,
                inputs={"project": [source]},
            )
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


def test_saved_qc_workflow_rejects_changed_priority_order(client: TestClient) -> None:
    """A saved workflow must reject swapped ranks without altering review decisions."""
    project = create_project(client, "QC saved ordering integrity")
    imported_ids: list[str] = []
    for name, size in (("priority-a.png", (80, 60)), ("priority-b.png", (81, 60))):
        imported = import_one(
            client,
            project["id"],
            filename=name,
            relative_path=f"qc-priority/{name}",
            size=size,
        )
        assert len(imported["successful"]) == 1
        imported_ids.append(imported["successful"][0]["image_id"])
    # Identical image bytes are deduplicated even with different filenames.
    assert len(set(imported_ids)) == 2

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
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{run['id']}")
    assert detail.status_code == 200, detail.text
    record = detail.json()
    qc_node = next(n for n in record["nodes"] if n["node_id"] == "qc")
    artifact = next(a for a in record["artifacts"] if a["data_type"] == "review_queue_reference")
    queue_id = artifact["payload_json"]["queue_id"]
    assert artifact["payload_json"]["review_status"] == "requires_researcher_review"

    with app.state.session_factory() as session:
        source = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.workflow_run_id == run["id"],
                WorkflowArtifact.data_type == "project_reference",
            )
        )
        node = session.get(WorkflowNodeRun, qc_node["id"])
        assert source is not None and node is not None
        params = {
            **dict(node.parameters_json or {}),
            "__workflow_run_id": run["id"],
            "__workflow_node_run_id": qc_node["id"],
        }
        rows = list(
            session.scalars(
                select(ReviewQueueItem)
                .where(ReviewQueueItem.review_queue_id == queue_id)
                .order_by(ReviewQueueItem.rank_position)
            )
        )
        assert len(rows) == 2
        rows[0].review_state = "in_progress"
        original_ranks = [item.rank_position for item in rows]
        rows[0].rank_position, rows[1].rank_position = 2, 1
        session.flush()
        with pytest.raises(ValidationError, match="snapshot failed integrity"):
            execute_runtime_adapter(
                "qc_review_queue",
                session=session,
                settings=app.state.settings,
                project_id=project["id"],
                parameters=params,
                inputs={"project": [source]},
            )
        assert rows[0].review_state == "in_progress"
        # Restore and prove ordinary retries still reuse the same queue.
        rows[0].rank_position, rows[1].rank_position = original_ranks
        session.flush()
        retried = execute_runtime_adapter(
            "qc_review_queue",
            session=session,
            settings=app.state.settings,
            project_id=project["id"],
            parameters=params,
            inputs={"project": [source]},
        )
        assert retried[0]["payload"]["queue_id"] == queue_id
