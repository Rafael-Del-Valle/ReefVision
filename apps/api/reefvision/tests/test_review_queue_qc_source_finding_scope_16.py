"""Reject corrupted QC source-finding scope/severity before review-queue writes."""

from __future__ import annotations

from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import QualityControlIssue, ReviewQueue, ReviewQueueItem
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.workflow_review_queue_integrity import validate_saved_queue_snapshot
from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_quality_control import run_quality_control, save_annotations
from reefvision.tests.test_review_queue_annotation_evidence_16 import (
    _queue_item,
    _saved_workflow_queue,
)


def _coral_qc_source(client: TestClient) -> tuple[str, str, str]:
    project = create_project(client, "QC source finding scope and severity")
    project_id = project["id"]
    imported = import_one(client, project_id, filename="finding-scope-coral.png")
    image_id = imported["successful"][0]["image_id"]
    class_id = project["label_classes"][0]["id"]
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
    qc = run_quality_control(client, project_id, {"rule_categories": ["annotation_geometry"]})
    assert qc["status"] == "succeeded"
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        issue = session.scalar(
            select(QualityControlIssue)
            .where(
                QualityControlIssue.quality_control_run_id == qc["id"],
                QualityControlIssue.image_id == image_id,
                QualityControlIssue.status.in_(("open", "acknowledged")),
            )
            .limit(1)
        )
        assert issue is not None
        return project_id, qc["id"], issue.id


def _set_corrupt_finding(
    client: TestClient, issue_id: str, field: str, foreign_project_id: str
) -> None:
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        issue = session.get(QualityControlIssue, issue_id)
        assert issue is not None
        if field == "severity":
            issue.severity = "critical"
        else:
            issue.project_id = foreign_project_id
        session.commit()


def _restore_finding(client: TestClient, issue_id: str, original_project_id: str) -> None:
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        issue = session.get(QualityControlIssue, issue_id)
        assert issue is not None
        issue.severity = "warning"
        issue.project_id = original_project_id
        session.commit()


@pytest.mark.parametrize("field", ["severity", "project"])
def test_standalone_qc_rejects_corrupt_source_finding_atomically(
    client: TestClient, field: str
) -> None:
    project_id, qc_id, issue_id = _coral_qc_source(client)
    foreign_project = create_project(client, "Different coral study")
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        issue = session.get(QualityControlIssue, issue_id)
        assert issue is not None
        original_severity = issue.severity

    endpoint = f"/api/v1/projects/{project_id}/review-queues"
    request = {"source_quality_control_run_id": qc_id}
    before = client.post(endpoint, json=request)
    assert before.status_code == 201, before.text
    baseline = _queue_item(client, before.json()["id"])
    _set_corrupt_finding(client, issue_id, field, foreign_project["id"])

    rejected = client.post(endpoint, json=request)
    assert rejected.status_code == 400, rejected.text
    assert "inconsistent scope or severity" in rejected.text
    queues = client.get(endpoint)
    assert queues.status_code == 200, queues.text
    assert len(queues.json()) == 1
    assert _queue_item(client, before.json()["id"]) == baseline

    _restore_finding(client, issue_id, project_id)
    if original_severity != "warning":
        with app.state.session_factory() as session:
            issue = session.get(QualityControlIssue, issue_id)
            assert issue is not None
            issue.severity = original_severity
            session.commit()
    recovered = client.post(endpoint, json=request)
    assert recovered.status_code == 201, recovered.text
    after = _queue_item(client, recovered.json()["id"])
    assert after["input_checksum"] == baseline["input_checksum"]
    assert after["review_state"] == "pending"


@pytest.mark.parametrize("field", ["severity", "project"])
def test_saved_qc_workflow_fails_closed_then_researcher_retries(
    client: TestClient, field: str
) -> None:
    project_id, _qc_id, issue_id = _coral_qc_source(client)
    foreign_project = create_project(client, "Foreign coral study for replay")
    baseline_id = _saved_workflow_queue(client, project_id, f"qc-source-before-{uuid4()}")
    baseline = _queue_item(client, baseline_id)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        issue = session.get(QualityControlIssue, issue_id)
        assert issue is not None
        original_severity = issue.severity

    graph = {
        "graph_id": f"qc-source-validation-{uuid4()}",
        "name": "Local QC source finding verification",
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
    _set_corrupt_finding(client, issue_id, field, foreign_project["id"])

    endpoint = f"/api/v1/projects/{project_id}/workflow-runs"
    queued = client.post(endpoint, json={"graph_record_id": saved.json()["id"]})
    assert queued.status_code == 202, queued.text
    assert not process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(queued.json()["job_id"])
    )
    failed = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert failed.status_code == 200, failed.text
    detail = failed.json()
    assert detail["run"]["status"] == "failed"
    assert "inconsistent scope or severity" in (detail["run"]["error_message"] or "")
    assert any(
        node["node_type"] == "qc_review_queue" and node["status"] == "failed"
        for node in detail["nodes"]
    )
    assert not [
        artifact
        for artifact in detail["artifacts"]
        if artifact["data_type"] == "review_queue_reference"
    ]
    with app.state.session_factory() as session:
        assert (
            len(
                session.scalars(
                    select(ReviewQueue).where(ReviewQueue.project_id == project_id)
                ).all()
            )
            == 1
        )

    _restore_finding(client, issue_id, project_id)
    if original_severity != "warning":
        with app.state.session_factory() as session:
            issue = session.get(QualityControlIssue, issue_id)
            assert issue is not None
            issue.severity = original_severity
            session.commit()

    queued = client.post(endpoint, json={"graph_record_id": saved.json()["id"]})
    assert queued.status_code == 202, queued.text
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(queued.json()["job_id"])
    )
    recovered = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["run"]["status"] == "succeeded"
    artifacts = [
        artifact
        for artifact in recovered.json()["artifacts"]
        if artifact["data_type"] == "review_queue_reference"
    ]
    assert len(artifacts) == 1
    payload = artifacts[0]["payload_json"]
    assert payload["priority_score_unit"] == "dimensionless"
    assert payload["review_status"] == "requires_researcher_review"
    assert _queue_item(client, payload["queue_id"])["input_checksum"] == baseline["input_checksum"]
    assert _queue_item(client, baseline_id)["review_state"] == "pending"
    with app.state.session_factory() as session:
        queue = session.get(ReviewQueue, baseline_id)
        assert queue is not None
        items = session.scalars(
            select(ReviewQueueItem).where(ReviewQueueItem.review_queue_id == baseline_id)
        ).all()
        validate_saved_queue_snapshot(queue, items)
        assert len(items) == 1
        assert items[0].review_state == "pending"
