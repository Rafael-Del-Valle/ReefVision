"""Persisted segmentation evaluations are available only to their project."""

from __future__ import annotations

from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import Job
from reefvision.tests.test_annotations import create_project


def test_scientific_evaluation_history_survives_session_and_is_project_scoped(
    client: TestClient,
) -> None:
    first = create_project(client, "Octocoral evaluation history")
    other = create_project(client, "Different project")
    app = cast(FastAPI, client.app)

    with app.state.session_factory() as session:
        own_waiting = Job(
            project_id=first["id"],
            job_type="segmentation_learning_evaluation",
            status="waiting",
            progress_current=0,
            progress_total=1,
            request_json={
                "task": "segment",
                "candidate_model_id": "candidate-1",
            },
            result_json={"promotion_eligible": False},
        )
        own_failed = Job(
            project_id=first["id"],
            job_type="segmentation_learning_evaluation",
            status="failed",
            progress_current=1,
            progress_total=1,
            request_json={
                "task": "segment",
                "candidate_model_id": "candidate-2",
            },
            result_json={
                "promotion_eligible": False,
                "blockers": ["Invalid scientific provenance"],
            },
        )
        unrelated = Job(
            project_id=first["id"],
            job_type="inference",
            status="succeeded",
            progress_current=1,
            progress_total=1,
            request_json={},
            result_json={},
        )
        foreign = Job(
            project_id=other["id"],
            job_type="segmentation_learning_evaluation",
            status="completed",
            progress_current=1,
            progress_total=1,
            request_json={"task": "segment"},
            result_json={"promotion_eligible": True},
        )
        session.add_all([own_waiting, own_failed, unrelated, foreign])
        session.commit()
        own_ids = {own_waiting.id, own_failed.id}
        foreign_id = foreign.id

    response = client.get(f"/api/v1/projects/{first['id']}/learning/segmentation/evaluations")
    assert response.status_code == 200, response.text
    records = response.json()
    assert {item["id"] for item in records} == own_ids
    assert foreign_id not in {item["id"] for item in records}
    assert {item["status"] for item in records} == {"waiting", "failed"}
    assert all(item["job_type"] == "segmentation_learning_evaluation" for item in records)
    assert any(item["result_json"]["blockers"] for item in records if item["status"] == "failed")


def test_segmentation_deployment_audit_is_project_scoped_and_read_only(
    client: TestClient,
) -> None:
    first = create_project(client, "Deployment audit first project")
    other = create_project(client, "Deployment audit other project")
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        promotion = Job(
            project_id=first["id"],
            job_type="segmentation_learning_deployment",
            status="succeeded",
            progress_current=1,
            progress_total=1,
            request_json={
                "task": "segment",
                "evaluation_id": "evaluation-1",
                "candidate_model_id": "candidate-1",
                "approved_by": "Scientist",
                "reason": "Approved verified mask evaluation",
            },
            result_json={"active_model_id": "candidate-1"},
        )
        rollback = Job(
            project_id=first["id"],
            job_type="segmentation_learning_deployment_rollback",
            status="succeeded",
            progress_current=1,
            progress_total=1,
            request_json={
                "task": "segment",
                "deployment_id": "promotion-1",
                "approved_by": "Scientist",
                "reason": "Reverted after scientific review",
            },
            result_json={
                "rolled_back_model_id": "candidate-1",
                "restored_model_id": None,
            },
        )
        unrelated = Job(
            project_id=first["id"],
            job_type="inference",
            status="succeeded",
            progress_current=1,
            progress_total=1,
            request_json={"task": "detect"},
            result_json={},
        )
        foreign = Job(
            project_id=other["id"],
            job_type="segmentation_learning_deployment",
            status="succeeded",
            progress_current=1,
            progress_total=1,
            request_json={"task": "segment"},
            result_json={},
        )
        session.add_all([promotion, rollback, unrelated, foreign])
        session.commit()
        allowed = {promotion.id, rollback.id}
        foreign_id = foreign.id

    response = client.get(f"/api/v1/projects/{first['id']}/learning/segmentation/deployments/audit")
    assert response.status_code == 200, response.text
    result = response.json()
    assert {item["id"] for item in result} == allowed
    assert foreign_id not in {item["id"] for item in result}
    assert all(item["status"] == "succeeded" for item in result)
    assert {item["job_type"] for item in result} == {
        "segmentation_learning_deployment",
        "segmentation_learning_deployment_rollback",
    }
    assert all(item["request_json"]["approved_by"] == "Scientist" for item in result)
