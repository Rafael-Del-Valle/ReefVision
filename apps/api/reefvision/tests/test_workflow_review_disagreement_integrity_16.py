"""Review disagreement handoffs must preserve the saved scientific provenance."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import Job, WorkflowArtifact, WorkflowNodeRun
from reefvision.domain.errors import ValidationError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.workflow_review import (
    _disagreement_artifact_for_consensus,
    _input_artifacts,
)
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_workflow_review_phase10 import _queue_seeded_review_run


def _seed_disagreement(client: TestClient, corruption: str | None) -> tuple[str, str, str, str]:
    project, run_id, job_id = _queue_seeded_review_run(client)
    project_id = str(project["id"])
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(app.state.settings, app.state.session_factory, job_id)
    detail = client.get(f"/api/v1/workflow-runs/{run_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "waiting_for_review"
    review_id = next(row["id"] for row in detail.json()["nodes"] if row["node_id"] == "review")
    with app.state.session_factory() as session:
        review = session.get(WorkflowNodeRun, review_id)
        assert review is not None
        consensus = session.get(WorkflowArtifact, review.input_artifact_ids_json[0])
        assert consensus is not None and consensus.data_type == "detection_consensus"
        producer = session.get(WorkflowNodeRun, consensus.producer_node_run_id)
        assert producer is not None
        payload = {
            "schema_version": "detection-consensus-0001",
            "project_id": project_id,
            "source_ids": [],
            "count": 0,
            "detections": [],
        }
        sibling = WorkflowArtifact(
            workflow_run_id=run_id,
            producer_node_run_id=producer.id,
            producer_port_id="disagreements",
            data_type="detection_disagreements",
            payload_json=payload,
            payload_sha256=canonical_json_sha256(payload),
        )
        session.add(sibling)
        session.flush()
        if corruption != "undeclared":
            producer.output_artifact_ids_json = [
                *producer.output_artifact_ids_json,
                sibling.id,
            ]
        if corruption == "changed_payload":
            sibling.payload_json = {**payload, "count": 999}
        elif corruption == "wrong_project":
            forged = {**payload, "project_id": "foreign-project"}
            sibling.payload_json = forged
            sibling.payload_sha256 = canonical_json_sha256(forged)
        elif corruption == "wrong_port":
            sibling.producer_port_id = "consensus"
        elif corruption == "wrong_type":
            sibling.data_type = "detection_proposals"
        elif corruption == "wrong_type_and_port":
            sibling.data_type = "detection_proposals"
            sibling.producer_port_id = "consensus"
        elif corruption == "duplicate_sibling":
            second = WorkflowArtifact(
                workflow_run_id=run_id,
                producer_node_run_id=producer.id,
                producer_port_id="disagreements",
                data_type="detection_disagreements",
                payload_json=payload,
                payload_sha256=canonical_json_sha256(payload),
            )
            session.add(second)
            session.flush()
            producer.output_artifact_ids_json = [
                *producer.output_artifact_ids_json,
                second.id,
            ]
        session.commit()
    return project_id, run_id, job_id, review_id


@pytest.mark.parametrize(
    ("corruption", "expected_error"),
    [
        ("undeclared", "omits persisted artifacts"),
        ("changed_payload", "disagreement handoff failed source provenance"),
        ("wrong_project", "disagreement handoff failed source provenance"),
        ("wrong_port", "disagreement handoff failed source provenance"),
        ("wrong_type", "disagreement handoff failed source provenance"),
        ("wrong_type_and_port", "disagreement handoff failed source provenance"),
        ("duplicate_sibling", "disagreement output is ambiguous"),
    ],
)
def test_saved_review_rejects_invalid_disagreement_lineage(
    client: TestClient, corruption: str, expected_error: str
) -> None:
    project_id, run_id, job_id, review_id = _seed_disagreement(client, corruption)
    app = cast(FastAPI, client.app)
    # Direct service checks and actual saved-workflow review API must agree.
    with app.state.session_factory() as session:
        review = session.get(WorkflowNodeRun, review_id)
        assert review is not None
        if corruption == "undeclared":
            with pytest.raises(ValidationError, match=expected_error):
                _input_artifacts(session, review, project_id=project_id)
        else:
            inputs = _input_artifacts(session, review, project_id=project_id)
            assert len(inputs) == 1
            with pytest.raises(ValidationError, match=expected_error):
                _disagreement_artifact_for_consensus(session, inputs[0], project_id=project_id)
    response = client.post(
        f"/api/v1/workflow-node-runs/{review_id}/resume-review",
        json={"reviewed_by": "scientist", "note": "Reject modified cohort"},
    )
    assert response.status_code == 400, response.text
    assert expected_error in response.json()["detail"]
    detail = client.get(f"/api/v1/workflow-runs/{run_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "waiting_for_review"
    review = next(row for row in detail.json()["nodes"] if row["id"] == review_id)
    assert review["status"] == "waiting_for_review"
    assert "review_approval" not in (review["result_json"] or {})
    with app.state.session_factory() as session:
        job = session.get(Job, job_id)
        assert job is not None and job.status == "waiting_for_review"


def test_saved_review_accepts_authentic_empty_disagreements(client: TestClient) -> None:
    project_id, run_id, job_id, review_id = _seed_disagreement(client, None)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        review = session.get(WorkflowNodeRun, review_id)
        assert review is not None
        inputs = _input_artifacts(session, review, project_id=project_id)
        assert len(inputs) == 1
        sibling = _disagreement_artifact_for_consensus(session, inputs[0], project_id=project_id)
        assert sibling is not None and sibling.data_type == "detection_disagreements"
    approval = client.post(
        f"/api/v1/workflow-node-runs/{review_id}/resume-review",
        json={"reviewed_by": "scientist", "note": "Verified empty disagreement set"},
    )
    assert approval.status_code == 202, approval.text
    assert approval.json()["status"] == "queued"
    detail = client.get(f"/api/v1/workflow-runs/{run_id}")
    assert detail.status_code == 200, detail.text
    review = next(row for row in detail.json()["nodes"] if row["id"] == review_id)
    assert review["result_json"]["review_approval"]["reviewed_by"] == "scientist"
    with app.state.session_factory() as session:
        job = session.get(Job, job_id)
        assert job is not None and job.status == "queued"
