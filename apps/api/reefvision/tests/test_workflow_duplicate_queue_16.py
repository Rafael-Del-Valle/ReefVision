"""Fail-closed replay when one saved QC workflow owns ambiguous evidence queues."""

from __future__ import annotations

from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import ReviewQueue, WorkflowArtifact, WorkflowNodeRun
from reefvision.domain.errors import ValidationError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.workflow_review_queue import create_review_queue_workflow_artifact
from reefvision.tests.test_annotations import create_project, import_one


def test_saved_qc_workflow_rejects_duplicate_owned_queues_without_erasing_review(
    client: TestClient,
) -> None:
    """A duplicate workflow owner must not make retries choose arbitrary scientific evidence."""
    project = create_project(client, "QC duplicate workflow ownership")
    project_id = project["id"]
    imported = import_one(
        client,
        project_id,
        filename="duplicate-owner-swiftia.png",
        relative_path="qc/duplicate-owner-swiftia.png",
    )
    assert len(imported["successful"]) == 1

    graph = {
        "graph_id": "qc-duplicate-owner-16",
        "name": "Duplicate owner replay safety",
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
    planned = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert planned.status_code == 200, planned.text
    assert planned.json()["valid"] and planned.json()["executable"]
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
    assert detail.json()["run"]["status"] == "succeeded"
    references = [
        item
        for item in detail.json()["artifacts"]
        if item["data_type"] == "review_queue_reference"
    ]
    assert len(references) == 1
    queue_id = references[0]["payload_json"]["queue_id"]
    assert references[0]["payload_json"]["priority_score_unit"] == "dimensionless"
    assert references[0]["payload_json"]["review_status"] == "requires_researcher_review"

    items = client.get(f"/api/v1/review-queues/{queue_id}/items")
    assert items.status_code == 200, items.text
    item_id = items.json()["items"][0]["id"]
    events_url = f"/api/v1/review-queues/{queue_id}/items/{item_id}/events"
    comment = client.post(
        events_url,
        json={
            "client_request_id": str(uuid4()),
            "event_type": "comment",
            "actor": "marine researcher",
            "comment": "Retain original Swiftia review provenance",
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
        original = session.get(ReviewQueue, queue_id)
        assert source is not None and node is not None and original is not None
        parameters = {
            **dict(node.parameters_json or {}),
            "__workflow_run_id": run_id,
            "__workflow_node_run_id": node.id,
        }
        replay_args = {
            "session": session,
            "settings": app.state.settings,
            "project_id": project_id,
            "parameters": parameters,
            "inputs": {"project": [source]},
        }
        # Establish that the original saved node is independently retryable.
        initial_replay = create_review_queue_workflow_artifact(**replay_args)
        assert initial_replay[0]["payload"]["queue_id"] == queue_id

        # Simulate a legacy race or manual database corruption. The second
        # record has the same workflow owner but no scientific items.
        duplicate = ReviewQueue(
            project_id=project_id,
            scope_type=original.scope_type,
            status=original.status,
            formula_id=original.formula_id,
            formula_version=original.formula_version,
            configuration_json=dict(original.configuration_json),
            input_checksums_json=dict(original.input_checksums_json),
            summary_json=dict(original.summary_json),
            item_count=original.item_count,
            created_by=original.created_by,
        )
        session.add(duplicate)
        session.commit()
        assert duplicate.id != original.id
        with pytest.raises(ValidationError, match="ambiguous duplicate workflow-owned queues"):
            create_review_queue_workflow_artifact(**replay_args)
        owners = session.scalars(
            select(ReviewQueue).where(
                ReviewQueue.project_id == project_id,
                ReviewQueue.created_by == original.created_by,
            )
        ).all()
        assert {queue.id for queue in owners} == {queue_id, duplicate.id}

    # A rejected retry cannot erase reviewer comments, approve annotations,
    # change original evidence, or delete either queue.
    history = client.get(events_url)
    assert history.status_code == 200, history.text
    assert history.json()["total"] == 1
    assert history.json()["items"][0]["id"] == comment.json()["id"]
    assert history.json()["requires_researcher_review"] is True
    annotations = client.get(f"/api/v1/images/{imported['successful'][0]['image_id']}/annotations")
    assert annotations.status_code == 200, annotations.text
    assert annotations.json()["annotations"] == []
