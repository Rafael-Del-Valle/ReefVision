"""Automatic mask-evaluation finalization remains isolated from model deployment."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import Job
from reefvision.jobs import worker
from reefvision.services.segmentation_evaluation_queue import SegmentationEvaluationQueueService
from reefvision.tests.test_annotations import create_project


def _waiting(
    client: TestClient,
    project_id: str,
    *,
    child_status: str,
) -> tuple[str, str]:
    with cast(FastAPI, client.app).state.session_factory() as session:
        parent = Job(
            project_id=project_id,
            job_type="segmentation_learning_evaluation",
            status="waiting",
            progress_current=0,
            progress_total=1,
            request_json={"task": "segment"},
        )
        session.add(parent)
        session.flush()
        child = Job(
            project_id=project_id,
            job_type="inference",
            status=child_status,
            progress_current=1 if child_status == "succeeded" else 0,
            progress_total=1,
            request_json={
                "model_id": "registered-segmenter",
                "model_task": "segment",
                "evaluation_only": True,
            },
        )
        session.add(child)
        session.flush()
        parent.request_json = {"task": "segment", "candidate_job_id": child.id}
        session.commit()
        return parent.id, child.id


def test_successful_terminal_inference_finalizes_original_record(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = create_project(client, "Auto segmentation eval success")
    evaluation_id, _ = _waiting(client, project["id"], child_status="succeeded")
    called: list[tuple[str, str]] = []

    def complete(self, project_id: str, record_id: str) -> Job:
        called.append((project_id, record_id))
        record = self.session.get(Job, record_id)
        assert record is not None
        record.status = "completed"
        self.session.commit()
        return record

    monkeypatch.setattr(SegmentationEvaluationQueueService, "advance", complete)
    app = cast(FastAPI, client.app)
    assert worker.process_next_waiting_segmentation_evaluation(
        app.state.settings, app.state.session_factory
    )
    assert called == [(project["id"], evaluation_id)]
    with app.state.session_factory() as session:
        record = session.get(Job, evaluation_id)
        assert record is not None and record.status == "completed"
    assert not worker.process_next_waiting_segmentation_evaluation(
        app.state.settings, app.state.session_factory
    )


def test_active_child_job_keeps_evaluation_waiting(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = create_project(client, "Auto segmentation eval pending")
    evaluation_id, _ = _waiting(client, project["id"], child_status="running")
    called: list[str] = []

    def unexpected(self, project_id: str, record_id: str) -> Job:
        called.append(record_id)
        raise RuntimeError("Active inference must not be finalized")

    monkeypatch.setattr(SegmentationEvaluationQueueService, "advance", unexpected)
    app = cast(FastAPI, client.app)
    assert not worker.process_next_waiting_segmentation_evaluation(
        app.state.settings, app.state.session_factory
    )
    assert called == []
    with app.state.session_factory() as session:
        record = session.get(Job, evaluation_id)
        assert record is not None and record.status == "waiting"


def test_failed_science_finalization_is_terminal_and_ineligible(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = create_project(client, "Auto segmentation eval fail closed")
    evaluation_id, _ = _waiting(client, project["id"], child_status="succeeded")

    def rejected(self, project_id: str, record_id: str) -> Job:
        raise ValueError("Corrupted raster checksum")

    monkeypatch.setattr(SegmentationEvaluationQueueService, "advance", rejected)
    app = cast(FastAPI, client.app)
    assert worker.process_next_waiting_segmentation_evaluation(
        app.state.settings, app.state.session_factory
    )
    with app.state.session_factory() as session:
        record = session.get(Job, evaluation_id)
        assert record is not None
        assert record.status == "failed"
        assert record.result_json["promotion_eligible"] is False
        assert record.completed_at is not None
    assert not worker.process_next_waiting_segmentation_evaluation(
        app.state.settings, app.state.session_factory
    )


def test_idle_worker_polls_waiting_scientific_evaluations(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = cast(FastAPI, client.app)
    calls: list[str] = []

    def fake_finalize(*_args: object) -> bool:
        calls.append("called")
        return True

    monkeypatch.setattr(worker, "process_next_waiting_segmentation_evaluation", fake_finalize)
    assert worker.process_next_thumbnail_job(app.state.settings, app.state.session_factory)
    assert calls == ["called"]


def test_completed_evaluation_after_32_active_parents_is_not_starved(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = create_project(client, "Auto segmentation eval fair polling")
    older_ids = [_waiting(client, project["id"], child_status="running")[0] for _ in range(33)]
    completed_id, _ = _waiting(client, project["id"], child_status="succeeded")
    app = cast(FastAPI, client.app)

    # Force deterministic page boundaries even on databases with coarse clocks.
    with app.state.session_factory() as session:
        for job_id in older_ids:
            job = session.get(Job, job_id)
            assert job is not None
            job.created_at = datetime(2020, 1, 1, tzinfo=UTC)
        completed = session.get(Job, completed_id)
        assert completed is not None
        completed.created_at = datetime(2021, 1, 1, tzinfo=UTC)
        session.commit()

    called: list[str] = []

    def complete(self, project_id: str, record_id: str) -> Job:
        called.append(record_id)
        record = self.session.get(Job, record_id)
        assert record is not None
        record.status = "completed"
        self.session.commit()
        return record

    monkeypatch.setattr(SegmentationEvaluationQueueService, "advance", complete)
    assert worker.process_next_waiting_segmentation_evaluation(
        app.state.settings, app.state.session_factory
    )
    assert called == [completed_id]
    with app.state.session_factory() as session:
        assert session.get(Job, completed_id).status == "completed"
        assert all(session.get(Job, job_id).status == "waiting" for job_id in older_ids)
