"""Stable SQLite identity for new QC workflow queues, without changing legacy IDs."""

from __future__ import annotations

from typing import cast
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from reefvision.db.models import ReviewQueue, WorkflowArtifact, WorkflowNodeRun
from reefvision.domain.errors import ValidationError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.review_queues import ReviewQueueCreateRequest
from reefvision.services.review_queues import ReviewQueueService
from reefvision.services.workflow_review_queue import create_review_queue_workflow_artifact
from reefvision.tests.test_annotations import create_project, import_one


def _expected_id(project_id: str, owner: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"reefvision:qc-queue:v1:{project_id}:{owner}"))


def test_new_workflow_queue_identity_prevents_duplicate_insert(
    client: TestClient,
) -> None:
    project = create_project(client, "Stable QC queue identity")
    project_id = project["id"]
    imported = import_one(
        client,
        project_id,
        filename="stable-identity-swiftia.png",
        relative_path="qc/stable-identity-swiftia.png",
    )
    assert len(imported["successful"]) == 1

    app = cast(FastAPI, client.app)
    owner = f"workflow:{uuid4()}:{uuid4()}"
    with app.state.session_factory() as session:
        service = ReviewQueueService(session, app.state.settings)
        first = service.create_queue_for_project(
            project_id, ReviewQueueCreateRequest(created_by=owner)
        )
        assert first.id == _expected_id(project_id, owner)
        assert first.item_count == 1
        # A second writer that missed the ownership lookup cannot commit a
        # second snapshot. The existing SQLite primary key is the arbiter.
        with pytest.raises(IntegrityError):
            service.create_queue_for_project(
                project_id, ReviewQueueCreateRequest(created_by=owner)
            )
        session.rollback()
        owned = session.scalars(
            select(ReviewQueue).where(
                ReviewQueue.project_id == project_id,
                ReviewQueue.created_by == owner,
            )
        ).all()
        assert [queue.id for queue in owned] == [first.id]

    # Standalone researchers may create independent historical snapshots.
    one = client.post(f"/api/v1/projects/{project_id}/review-queues", json={})
    two = client.post(f"/api/v1/projects/{project_id}/review-queues", json={})
    assert one.status_code == two.status_code == 201
    assert one.json()["id"] != two.json()["id"]
    assert one.json()["id"] != first.id
    assert two.json()["id"] != first.id


def test_saved_workflow_queue_collision_fails_closed_then_replays(
    client: TestClient,
) -> None:
    project = create_project(client, "QC saved-run collision recovery")
    project_id = project["id"]
    imported = import_one(
        client,
        project_id,
        filename="workflow-collision-swiftia.png",
        relative_path="qc/workflow-collision-swiftia.png",
    )
    assert len(imported["successful"]) == 1
    graph = {
        "graph_id": "qc-stable-owner-16",
        "name": "Stable QC owner and review",
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
    plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["valid"] and plan.json()["executable"]
    saved = client.post(f"/api/v1/projects/{project_id}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    queued = client.post(
        f"/api/v1/projects/{project_id}/workflow-runs",
        json={"graph_record_id": saved.json()["id"]},
    )
    assert queued.status_code == 202, queued.text
    run_id = queued.json()["id"]
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(queued.json()["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{run_id}")
    assert detail.status_code == 200, detail.text
    outputs = [
        artifact
        for artifact in detail.json()["artifacts"]
        if artifact["data_type"] == "review_queue_reference"
    ]
    assert len(outputs) == 1
    output = outputs[0]
    queue_id = output["payload_json"]["queue_id"]
    assert output["payload_json"]["priority_score_unit"] == "dimensionless"
    assert output["payload_json"]["review_status"] == "requires_researcher_review"

    item_page = client.get(f"/api/v1/review-queues/{queue_id}/items")
    assert item_page.status_code == 200, item_page.text
    item_id = item_page.json()["items"][0]["id"]
    events_url = f"/api/v1/review-queues/{queue_id}/items/{item_id}/events"
    comment = client.post(
        events_url,
        json={
            "client_request_id": str(uuid4()),
            "event_type": "comment",
            "actor": "coral researcher",
            "comment": "Preserve the original review evidence",
        },
    )
    assert comment.status_code == 201, comment.text

    with app.state.session_factory() as session:
        source = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.workflow_run_id == run_id,
                WorkflowArtifact.data_type == "project_reference",
            )
        )
        node = session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_type == "qc_review_queue",
            )
        )
        queue = session.get(ReviewQueue, queue_id)
        assert source is not None and node is not None and queue is not None
        owner = queue.created_by
        assert owner == f"workflow:{run_id}:{node.id}"
        assert queue_id == _expected_id(project_id, owner)
        params = {
            **dict(node.parameters_json or {}),
            "__workflow_run_id": run_id,
            "__workflow_node_run_id": node.id,
        }
        original_outputs = list(node.output_artifact_ids_json)
        assert original_outputs == [output["id"]]
        # Simulate interrupted creation plus an ownership-damaged original.
        # The stable PK must prevent a replacement scientific snapshot even
        # when the normal created_by lookup cannot find the original queue.
        node.output_artifact_ids_json = []
        queue.created_by = "local_user"
        session.commit()
        with pytest.raises(ValidationError, match="Concurrent QC review-queue creation"):
            create_review_queue_workflow_artifact(
                session=session,
                settings=app.state.settings,
                project_id=project_id,
                parameters=params,
                inputs={"project": [source]},
            )
        # The failed flush has been rolled back, leaving original evidence.
        assert session.get(ReviewQueue, queue_id) is not None
        assert session.scalar(
            select(ReviewQueue).where(ReviewQueue.id == queue_id)
        ).created_by == "local_user"
        queue = session.get(ReviewQueue, queue_id)
        node = session.get(WorkflowNodeRun, node.id)
        assert queue is not None and node is not None
        queue.created_by = owner
        node.output_artifact_ids_json = original_outputs
        session.commit()
        replay = create_review_queue_workflow_artifact(
            session=session,
            settings=app.state.settings,
            project_id=project_id,
            parameters=params,
            inputs={"project": [source]},
        )
        assert replay[0]["payload"]["queue_id"] == queue_id
        assert replay[0]["payload"]["review_status"] == "requires_researcher_review"

    history = client.get(events_url)
    assert history.status_code == 200, history.text
    assert history.json()["total"] == 1
    assert history.json()["items"][0]["id"] == comment.json()["id"]
    annotations = client.get(f"/api/v1/images/{imported['successful'][0]['image_id']}/annotations")
    assert annotations.status_code == 200, annotations.text
    assert annotations.json()["annotations"] == []
