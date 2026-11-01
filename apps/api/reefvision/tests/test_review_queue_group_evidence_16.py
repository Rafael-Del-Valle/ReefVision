"""QC evidence must track biological grouping without changing review priority."""

from __future__ import annotations

from typing import cast
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import ImageAsset, ReviewQueue, ReviewQueueItem
from reefvision.services.workflow_review_queue_integrity import validate_saved_queue_snapshot
from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_review_queue_annotation_evidence_16 import (
    _queue_item,
    _saved_workflow_queue,
)


def test_group_reassignment_changes_new_qc_evidence_not_saved_review_history(
    client: TestClient,
) -> None:
    project = create_project(client, "Coral tank identity evidence")
    project_id = project["id"]
    imported = import_one(client, project_id, filename="tank-coral.png")
    image_id = imported["successful"][0]["image_id"]
    app = cast(FastAPI, client.app)

    with app.state.session_factory() as session:
        image = session.get(ImageAsset, image_id)
        assert image is not None
        original_updated_at = image.updated_at
        image.group_key = "tank-A"
        image.updated_at = original_updated_at
        session.commit()

    before = client.post(f"/api/v1/projects/{project_id}/review-queues", json={})
    assert before.status_code == 201, before.text
    original = _queue_item(client, before.json()["id"])
    first_workflow_id = _saved_workflow_queue(
        client, project_id, f"qc-tank-before-{uuid4()}"
    )
    saved_original = _queue_item(client, first_workflow_id)
    assert saved_original["input_checksum"] == original["input_checksum"]

    # Both values are nonempty, so the missing-group priority signal is
    # unchanged. A different tank still changes the scientific evidence.
    with app.state.session_factory() as session:
        image = session.get(ImageAsset, image_id)
        assert image is not None
        image.group_key = "tank-B"
        image.updated_at = original_updated_at
        session.commit()

    after = client.post(f"/api/v1/projects/{project_id}/review-queues", json={})
    assert after.status_code == 201, after.text
    updated = _queue_item(client, after.json()["id"])
    assert updated["score"] == original["score"]
    assert updated["input_checksum"] != original["input_checksum"]
    assert (
        _queue_item(client, first_workflow_id)["input_checksum"]
        == saved_original["input_checksum"]
    )

    second_workflow_id = _saved_workflow_queue(
        client, project_id, f"qc-tank-after-{uuid4()}"
    )
    assert _queue_item(client, second_workflow_id)["input_checksum"] == updated[
        "input_checksum"
    ]
    with app.state.session_factory() as session:
        historical_queue = session.get(ReviewQueue, first_workflow_id)
        assert historical_queue is not None
        historical_items = session.scalars(
            select(ReviewQueueItem).where(
                ReviewQueueItem.review_queue_id == first_workflow_id
            )
        ).all()
        validate_saved_queue_snapshot(historical_queue, historical_items)
        assert historical_items[0].review_state == "pending"
