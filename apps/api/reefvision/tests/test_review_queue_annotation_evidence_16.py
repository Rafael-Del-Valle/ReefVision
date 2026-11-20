"""QC snapshots must distinguish edits that leave biological object counts unchanged."""

from __future__ import annotations

from typing import cast
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import ReviewQueue, ReviewQueueItem
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.workflow_review_queue_integrity import validate_saved_queue_snapshot
from reefvision.tests.test_annotations import create_project, import_one


def _queue_item(client: TestClient, queue_id: str) -> dict:
    response = client.get(f"/api/v1/review-queues/{queue_id}/items")
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    return response.json()["items"][0]


def _saved_workflow_queue(client: TestClient, project_id: str, graph_id: str) -> str:
    graph = {
        "graph_id": graph_id,
        "name": "Immutable coral annotation evidence",
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
    app = cast(FastAPI, client.app)
    queued = client.post(
        f"/api/v1/projects/{project_id}/workflow-runs",
        json={"graph_record_id": saved.json()["id"]},
    )
    assert queued.status_code == 202, queued.text
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(queued.json()["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert detail.status_code == 200, detail.text
    outputs = [
        artifact
        for artifact in detail.json()["artifacts"]
        if artifact["data_type"] == "review_queue_reference"
    ]
    assert len(outputs) == 1
    payload = outputs[0]["payload_json"]
    assert payload["priority_score_unit"] == "dimensionless"
    assert payload["review_status"] == "requires_researcher_review"
    return str(payload["queue_id"])


def test_standalone_and_saved_qc_queues_bind_annotation_geometry_without_rewriting_history(
    client: TestClient,
) -> None:
    project = create_project(client, "QC coral evidence fingerprint")
    project_id = project["id"]
    imported = import_one(
        client,
        project_id,
        filename="coral-geometry.png",
        relative_path="qc/coral-geometry.png",
    )
    image_id = imported["successful"][0]["image_id"]
    annotation_id = str(uuid4())
    label_class_id = project["label_classes"][0]["id"]
    url = f"/api/v1/images/{image_id}/annotations"

    def save_annotation(revision: int, x_min: float) -> None:
        response = client.put(
            url,
            json={
                "base_revision": revision,
                "annotation_status": "annotated",
                "annotations": [
                    {
                        "id": annotation_id,
                        "label_class_id": label_class_id,
                        "x_min": x_min,
                        "y_min": 5,
                        "x_max": x_min + 20,
                        "y_max": 25,
                    }
                ],
            },
        )
        assert response.status_code == 200, response.text

    save_annotation(0, 5)
    before = client.post(f"/api/v1/projects/{project_id}/review-queues", json={})
    assert before.status_code == 201, before.text
    original = _queue_item(client, before.json()["id"])
    workflow_id = _saved_workflow_queue(client, project_id, f"qc-evidence-{uuid4()}")
    saved_original = _queue_item(client, workflow_id)
    assert saved_original["input_checksum"] == original["input_checksum"]

    # Moving a box must not look like identical input evidence merely because
    # its count, class, and review state are unchanged.
    save_annotation(1, 12)
    after = client.post(f"/api/v1/projects/{project_id}/review-queues", json={})
    assert after.status_code == 201, after.text
    updated = _queue_item(client, after.json()["id"])
    assert updated["label_class_ids_json"] == original["label_class_ids_json"]
    assert updated["input_checksum"] != original["input_checksum"]
    assert _queue_item(client, workflow_id)["input_checksum"] == saved_original["input_checksum"]

    # A new executable saved workflow run must use the changed evidence while
    # its predecessor remains a valid immutable, unapproved research snapshot.
    newer_workflow_id = _saved_workflow_queue(client, project_id, f"qc-evidence-after-{uuid4()}")
    assert _queue_item(client, newer_workflow_id)["input_checksum"] == updated["input_checksum"]
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        queue = session.get(ReviewQueue, workflow_id)
        assert queue is not None
        items = session.scalars(
            select(ReviewQueueItem).where(ReviewQueueItem.review_queue_id == workflow_id)
        ).all()
        validate_saved_queue_snapshot(queue, items)
        assert items[0].review_state == "pending"
