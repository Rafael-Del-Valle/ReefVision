"""Concurrent local scientists must not approve one saved review gate twice."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event, current_thread
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import Job, WorkflowNodeRun
from reefvision.domain.errors import ConflictError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.workflow_execution import WorkflowReviewResumeRequest
from reefvision.services import workflow_review
from reefvision.tests.test_workflow_review_phase10 import _queue_seeded_review_run


def _waiting_saved_review(client: TestClient) -> tuple[FastAPI, str, str, str]:
    _, run_id, job_id = _queue_seeded_review_run(client)
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(app.state.settings, app.state.session_factory, job_id)
    detail = client.get(f"/api/v1/workflow-runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["run"]["status"] == "waiting_for_review"
    review_id = next(
        node["id"] for node in detail.json()["nodes"] if node["node_id"] == "review"
    )
    return app, run_id, job_id, review_id


def test_saved_review_two_local_approvals_are_one_decision(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, run_id, job_id, review_id = _waiting_saved_review(client)
    first_has_writer_turn = Event()
    release_first = Event()
    second_started = Event()
    second_saw_inputs = Event()
    original_inputs = workflow_review._input_artifacts

    def controlled_inputs(session, node_run, *, project_id):
        if current_thread().name == "first-scientist":
            first_has_writer_turn.set()
            assert release_first.wait(timeout=10), "First reviewer did not resume"
        if current_thread().name == "second-scientist":
            second_saw_inputs.set()
        return original_inputs(session, node_run, project_id=project_id)

    monkeypatch.setattr(workflow_review, "_input_artifacts", controlled_inputs)

    def attempt(identity: str) -> tuple[str, str]:
        current_thread().name = identity
        if identity == "second-scientist":
            second_started.set()
        with app.state.session_factory() as session:
            try:
                result = workflow_review.resume_review_gate(
                    session,
                    review_id,
                    WorkflowReviewResumeRequest(
                        reviewed_by=identity,
                        note="Verified the original saved scientific evidence",
                    ),
                )
            except ConflictError as exc:
                return ("conflict", str(exc))
        return ("approved", result.status)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(attempt, "first-scientist")
        try:
            assert first_has_writer_turn.wait(timeout=10)
            second = executor.submit(attempt, "second-scientist")
            assert second_started.wait(timeout=10)
            # The second reviewer must not inspect stale inputs while the first
            # transaction holds the SQLite writer turn. A busy 409 is acceptable.
            assert not second_saw_inputs.wait(timeout=0.15)
        finally:
            release_first.set()
        assert first.result(timeout=20) == ("approved", "queued")
        second_outcome = second.result(timeout=20)
        assert second_outcome[0] == "conflict"
        assert "not waiting for review" in second_outcome[1] or "busy" in second_outcome[1]

    detail = client.get(f"/api/v1/workflow-runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["run"]["status"] == "queued"
    review = next(
        node for node in detail.json()["nodes"] if node["id"] == review_id
    )
    assert review["status"] == "review_approved"
    assert review["result_json"]["review_approval"]["reviewed_by"] == "first-scientist"
    with app.state.session_factory() as session:
        job = session.get(Job, job_id)
        assert job is not None
        assert job.status == "queued"


def test_saved_review_rejects_stale_read_transaction(
    client: TestClient,
) -> None:
    app, run_id, job_id, review_id = _waiting_saved_review(client)
    with app.state.session_factory() as session:
        connection = session.connection()
        connection.exec_driver_sql("BEGIN")
        assert session.scalar(
            select(WorkflowNodeRun.status).where(WorkflowNodeRun.id == review_id)
        ) == "waiting_for_review"
        with pytest.raises(ConflictError, match="fresh transaction"):
            workflow_review.resume_review_gate(
                session,
                review_id,
                WorkflowReviewResumeRequest(
                    reviewed_by="second-scientist",
                    note="Must re-read from a fresh snapshot",
                ),
            )
        session.rollback()

    detail = client.get(f"/api/v1/workflow-runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["run"]["status"] == "waiting_for_review"
    review = next(
        node for node in detail.json()["nodes"] if node["id"] == review_id
    )
    assert review["status"] == "waiting_for_review"
    assert "review_approval" not in (review["result_json"] or {})
    with app.state.session_factory() as session:
        job = session.get(Job, job_id)
        assert job is not None
        assert job.status == "waiting_for_review"
