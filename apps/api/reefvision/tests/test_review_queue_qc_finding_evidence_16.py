"""QC finding detail must be fingerprinted even when review priority is unchanged."""

from __future__ import annotations

from typing import cast
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import QualityControlIssue, ReviewQueue, ReviewQueueItem
from reefvision.services.workflow_review_queue_integrity import validate_saved_queue_snapshot
from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_quality_control import run_quality_control, save_annotations
from reefvision.tests.test_review_queue_annotation_evidence_16 import (
    _queue_item,
    _saved_workflow_queue,
)


def test_qc_finding_diagnostics_change_new_standalone_and_saved_workflow_evidence(
    client: TestClient,
) -> None:
    project = create_project(client, "Coral finding source provenance")
    project_id = project["id"]
    imported = import_one(client, project_id, filename="coral-qc-finding.png")
    image_id = imported["successful"][0]["image_id"]
    class_id = project["label_classes"][0]["id"]

    # Two overlapping biological counts produce a deterministic source QC
    # finding. Both saved workflows and standalone queues use the same source.
    save_annotations(
        client,
        image_id,
        base_revision=0,
        annotation_status="reviewed",
        annotations=[
            {
                "id": str(uuid4()),
                "label_class_id": class_id,
                "x_min": 5,
                "y_min": 5,
                "x_max": 25,
                "y_max": 25,
            },
            {
                "id": str(uuid4()),
                "label_class_id": class_id,
                "x_min": 5,
                "y_min": 5,
                "x_max": 25,
                "y_max": 25,
            },
        ],
    )
    qc = run_quality_control(
        client,
        project_id,
        {"rule_categories": ["annotation_geometry"]},
    )
    assert qc["status"] == "succeeded"

    url = f"/api/v1/projects/{project_id}/review-queues"

    def standalone_item() -> dict:
        response = client.post(url, json={"source_quality_control_run_id": qc["id"]})
        assert response.status_code == 201, response.text
        return _queue_item(client, response.json()["id"])

    before = standalone_item()
    first_workflow_id = _saved_workflow_queue(client, project_id, f"qc-finding-before-{uuid4()}")
    historical = _queue_item(client, first_workflow_id)
    assert historical["input_checksum"] == before["input_checksum"]

    app = cast(FastAPI, client.app)
    private_note = "confidential biological site coordinates"
    with app.state.session_factory() as session:
        issues = session.scalars(
            select(QualityControlIssue).where(
                QualityControlIssue.quality_control_run_id == qc["id"],
                QualityControlIssue.image_id == image_id,
            )
        ).all()
        source_issues = [issue for issue in issues if issue.status in {"open", "acknowledged"}]
        assert source_issues
        issue = source_issues[0]
        issue.explanation = private_note
        issue.measured_values_json = {
            **issue.measured_values_json,
            "independent_observer_count": 2,
        }
        issue.thresholds_json = {**issue.thresholds_json, "audit_reference": 0.8}
        session.commit()

    # The same issue IDs, maximum severity and weighted QC priority must
    # still produce a different scientific input fingerprint.
    after = standalone_item()
    assert after["score"] == before["score"]
    assert after["related_issue_ids_json"] == before["related_issue_ids_json"]
    assert after["input_checksum"] != before["input_checksum"]
    second_workflow_id = _saved_workflow_queue(client, project_id, f"qc-finding-after-{uuid4()}")
    current = _queue_item(client, second_workflow_id)
    assert current["input_checksum"] == after["input_checksum"]
    assert _queue_item(client, first_workflow_id)["input_checksum"] == historical["input_checksum"]
    assert private_note not in str(after)
    assert private_note not in str(current)

    # Previously created records retain their own immutable, unapproved
    # evidence and pass the same saved-workflow integrity verification.
    with app.state.session_factory() as session:
        queue = session.get(ReviewQueue, first_workflow_id)
        assert queue is not None
        items = session.scalars(
            select(ReviewQueueItem).where(ReviewQueueItem.review_queue_id == first_workflow_id)
        ).all()
        validate_saved_queue_snapshot(queue, items)
        assert len(items) == 1
        assert items[0].review_state == "pending"
