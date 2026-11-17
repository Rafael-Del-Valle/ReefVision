"""Verified coral mask changes must survive standalone and saved QC provenance.

All fixtures use disposable application databases. Neither an immutable
dataset version nor historical researcher review actions may be rewritten.
"""

from __future__ import annotations

from typing import cast
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import ReviewQueue, ReviewQueueItem
from reefvision.services.workflow_review_queue_integrity import validate_saved_queue_snapshot
from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_dataset_versions import create_version
from reefvision.tests.test_mask_dataset_exports import _save_polygon
from reefvision.tests.test_review_queue_annotation_evidence_16 import (
    _queue_item,
    _saved_workflow_queue,
)
from reefvision.tests.test_workflow_review_queue_frozen_dataset_16 import (
    _frozen_graph,
    _run_frozen_graph,
)


def _create_queue(client: TestClient, url: str) -> dict:
    result = client.post(url, json={})
    assert result.status_code == 201, result.text
    return _queue_item(client, result.json()["id"])


def test_mask_geometry_fingerprints_standalone_and_executable_saved_qc(
    client: TestClient,
) -> None:
    project = create_project(client, "Polyp mask provenance QC")
    project_id = project["id"]
    imported = import_one(client, project_id, filename="polyp-mask-evidence.png")
    image_id = imported["successful"][0]["image_id"]
    class_id = project["label_classes"][0]["id"]
    mask_id = str(uuid4())

    # Both masks have exactly the same extent, class, image and object count.
    # An unchanged bounding box or QC priority must not hide a changed polygon.
    first_polygon = [(8, 8), (32, 8), (32, 32), (8, 32)]
    second_polygon = [(8, 8), (32, 8), (25, 32), (8, 32)]
    _save_polygon(
        client,
        image_id=image_id,
        class_id=class_id,
        mask_id=mask_id,
        points=first_polygon,
        base_revision=0,
    )
    version_id = create_version(client, project_id, name="Frozen mask study")["id"]
    project_url = f"/api/v1/projects/{project_id}/review-queues"
    version_url = f"/api/v1/dataset-versions/{version_id}/review-queues"

    live_before = _create_queue(client, project_url)
    frozen_before = _create_queue(client, version_url)
    saved_live_before = _queue_item(
        client, _saved_workflow_queue(client, project_id, f"qc-mask-before-{uuid4()}")
    )
    frozen_graph = _frozen_graph(version_id)
    saved_graph = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs",
        json={"graph": frozen_graph},
    )
    assert saved_graph.status_code == 201, saved_graph.text
    _, workflow_before = _run_frozen_graph(client, project_id, saved_graph.json()["id"])
    saved_frozen_before = _queue_item(client, workflow_before["queue_id"])

    assert live_before["input_checksum"] == saved_live_before["input_checksum"]
    assert frozen_before["input_checksum"] == saved_frozen_before["input_checksum"]
    # Live queues retain temporal signals that the frozen version cannot infer.
    assert workflow_before["priority_score_unit"] == "dimensionless"
    assert workflow_before["review_status"] == "requires_researcher_review"

    _save_polygon(
        client,
        image_id=image_id,
        class_id=class_id,
        mask_id=mask_id,
        points=second_polygon,
        base_revision=1,
    )
    live_after = _create_queue(client, project_url)
    frozen_after = _create_queue(client, version_url)
    saved_live_after = _queue_item(
        client, _saved_workflow_queue(client, project_id, f"qc-mask-after-{uuid4()}")
    )
    _, workflow_after = _run_frozen_graph(client, project_id, saved_graph.json()["id"])
    saved_frozen_after = _queue_item(client, workflow_after["queue_id"])

    assert live_after["input_checksum"] != live_before["input_checksum"]
    assert live_after["input_checksum"] == saved_live_after["input_checksum"]
    assert frozen_after["input_checksum"] == frozen_before["input_checksum"]
    assert saved_frozen_after["input_checksum"] == saved_frozen_before["input_checksum"]
    assert live_after["score"] == live_before["score"]
    assert frozen_after["score"] == frozen_before["score"]
    assert saved_live_before["input_checksum"] == live_before["input_checksum"]
    assert workflow_after["review_status"] == "requires_researcher_review"

    # The new queue's scientific input checksum is immutable; no mask change
    # can turn an older saved workflow into an automatically accepted result.
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        for queue_id in (workflow_before["queue_id"], workflow_after["queue_id"]):
            queue = session.get(ReviewQueue, queue_id)
            assert queue is not None
            items = session.scalars(
                select(ReviewQueueItem).where(ReviewQueueItem.review_queue_id == queue_id)
            ).all()
            assert len(items) == 1
            assert items[0].review_state == "pending"
            validate_saved_queue_snapshot(queue, items)
