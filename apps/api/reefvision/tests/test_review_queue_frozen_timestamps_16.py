"""Frozen QC queues must not rank later mutable image timestamps as snapshot evidence."""

from __future__ import annotations

from datetime import timedelta
from typing import cast
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import ImageAsset, ReviewQueue, ReviewQueueItem
from reefvision.services.workflow_review_queue_integrity import validate_saved_queue_snapshot
from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_dataset_versions import create_version, save_annotations
from reefvision.tests.test_review_queue_annotation_evidence_16 import (
    _queue_item,
    _saved_workflow_queue,
)


def test_version_queue_ignores_later_live_import_time_and_workflow_tracks_live_change(
    client: TestClient,
) -> None:
    project = create_project(client, "Frozen octocoral import chronology")
    project_id = project["id"]
    imported = import_one(client, project_id, filename="chronology-coral.png")
    image_id = imported["successful"][0]["image_id"]
    save_annotations(
        client,
        image_id,
        base_revision=0,
        annotation_status="reviewed",
        annotations=[
            {
                "id": str(uuid4()),
                "label_class_id": project["label_classes"][0]["id"],
                "x_min": 5,
                "y_min": 5,
                "x_max": 25,
                "y_max": 25,
            }
        ],
    )
    version = create_version(client, project_id, name="Frozen chronology")
    version_url = f"/api/v1/dataset-versions/{version['id']}/review-queues"
    project_url = f"/api/v1/projects/{project_id}/review-queues"

    def new_item(url: str) -> dict:
        response = client.post(url, json={})
        assert response.status_code == 201, response.text
        return _queue_item(client, response.json()["id"])

    frozen_before = new_item(version_url)
    project_before = new_item(project_url)
    workflow_before_id = _saved_workflow_queue(
        client, project_id, f"qc-live-time-before-{uuid4()}"
    )
    workflow_before = _queue_item(client, workflow_before_id)
    assert workflow_before["input_checksum"] == project_before["input_checksum"]
    assert frozen_before["signal_values_json"]["recent_import"] == 0.0
    assert frozen_before["signal_values_json"]["stale_review_state"] == 0.0
    assert project_before["signal_values_json"]["recent_import"] > 0.0

    # The stored version has no per-image timestamp snapshot. Changing only
    # the live import timestamp must not rewrite its scientific priority.
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        image = session.get(ImageAsset, image_id)
        assert image is not None
        assert image.created_at is not None
        image.created_at -= timedelta(days=45)
        session.commit()

    frozen_after = new_item(version_url)
    project_after = new_item(project_url)
    assert frozen_after["signal_values_json"] == frozen_before["signal_values_json"]
    assert frozen_after["score"] == frozen_before["score"]
    assert frozen_after["input_checksum"] == frozen_before["input_checksum"]
    assert project_after["signal_values_json"]["recent_import"] == 0.0
    assert project_after["score"] < project_before["score"]
    assert project_after["input_checksum"] != project_before["input_checksum"]

    workflow_after_id = _saved_workflow_queue(
        client, project_id, f"qc-live-time-after-{uuid4()}"
    )
    workflow_after = _queue_item(client, workflow_after_id)
    assert workflow_after["input_checksum"] == project_after["input_checksum"]
    assert _queue_item(client, workflow_before_id)["input_checksum"] == workflow_before[
        "input_checksum"
    ]
    with app.state.session_factory() as session:
        queue = session.get(ReviewQueue, workflow_before_id)
        assert queue is not None
        items = session.scalars(
            select(ReviewQueueItem).where(
                ReviewQueueItem.review_queue_id == workflow_before_id
            )
        ).all()
        validate_saved_queue_snapshot(queue, items)
        assert items[0].review_state == "pending"
