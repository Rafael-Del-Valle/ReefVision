"""QC evidence fingerprints must track unverified prediction geometry, not just IDs."""

from __future__ import annotations

from typing import cast
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import (
    Job,
    ModelRegistration,
    PredictionProposal,
    ReviewQueue,
    ReviewQueueItem,
)
from reefvision.services.workflow_review_queue_integrity import validate_saved_queue_snapshot
from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_review_queue_annotation_evidence_16 import (
    _queue_item,
    _saved_workflow_queue,
)


def test_prediction_box_edit_changes_standalone_and_saved_workflow_qc_evidence(
    client: TestClient,
) -> None:
    project = create_project(client, "Unverified coral prediction evidence")
    project_id = project["id"]
    imported = import_one(client, project_id, filename="prediction-coral.png")
    image_id = imported["successful"][0]["image_id"]
    class_id = project["label_classes"][0]["id"]
    model_id, job_id, prediction_id = (str(uuid4()) for _ in range(3))
    model_checksum = "c" * 64

    # Synthetic local registration and prediction metadata only: no model
    # checkpoint, external weight download, or verified annotation is created.
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        session.add(
            ModelRegistration(
                id=model_id,
                project_id=project_id,
                purpose="detection",
                display_name="Synthetic QC prediction",
                source_filename="synthetic-qc.pt",
                managed_path=f"models/synthetic-{model_id}.pt",
                sha256=model_checksum,
                file_size_bytes=0,
                framework="test",
                task="detect",
                provider_name="local_test",
                provider_version="1",
                class_map_json={},
            )
        )
        session.add(
            Job(
                id=job_id,
                project_id=project_id,
                job_type="inference",
                status="succeeded",
                request_json={},
            )
        )
        session.flush()
        session.add(
            PredictionProposal(
                id=prediction_id,
                project_id=project_id,
                image_id=image_id,
                model_id=model_id,
                inference_job_id=job_id,
                model_checksum=model_checksum,
                label_class_id=class_id,
                predicted_label="Muricea Closed",
                predicted_index=0,
                confidence=0.75,
                x_min=5,
                y_min=6,
                x_max=25,
                y_max=26,
                review_status="pending",
                was_edited=False,
                provenance_json={"source": "synthetic_test"},
            )
        )
        session.commit()

    before = client.post(f"/api/v1/projects/{project_id}/review-queues", json={})
    assert before.status_code == 201, before.text
    original = _queue_item(client, before.json()["id"])
    original_workflow_id = _saved_workflow_queue(
        client, project_id, f"qc-prediction-before-{uuid4()}"
    )
    saved_original = _queue_item(client, original_workflow_id)
    assert saved_original["input_checksum"] == original["input_checksum"]

    with app.state.session_factory() as session:
        prediction = session.get(PredictionProposal, prediction_id)
        assert prediction is not None
        prediction.x_min = 12
        prediction.x_max = 32
        session.commit()

    after = client.post(f"/api/v1/projects/{project_id}/review-queues", json={})
    assert after.status_code == 201, after.text
    updated = _queue_item(client, after.json()["id"])
    assert updated["score"] == original["score"]
    assert updated["model_ids_json"] == original["model_ids_json"]
    assert updated["input_checksum"] != original["input_checksum"]
    assert _queue_item(client, original_workflow_id)["input_checksum"] == saved_original[
        "input_checksum"
    ]

    newer_workflow_id = _saved_workflow_queue(
        client, project_id, f"qc-prediction-after-{uuid4()}"
    )
    assert _queue_item(client, newer_workflow_id)["input_checksum"] == updated["input_checksum"]
    with app.state.session_factory() as session:
        historical_queue = session.get(ReviewQueue, original_workflow_id)
        assert historical_queue is not None
        historical_items = session.scalars(
            select(ReviewQueueItem).where(
                ReviewQueueItem.review_queue_id == original_workflow_id
            )
        ).all()
        validate_saved_queue_snapshot(historical_queue, historical_items)
        assert historical_items[0].review_state == "pending"
