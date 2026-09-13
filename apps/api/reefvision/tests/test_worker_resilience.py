from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from reefvision.db.models import Job
from reefvision.jobs import worker
from reefvision.tests.test_annotations import create_project


def _queued_job(client: TestClient, project_id: str, job_type: str) -> str:
    with client.app.state.session_factory() as session:
        job = Job(
            project_id=project_id,
            job_type=job_type,
            status="queued",
            progress_current=0,
            progress_total=0,
            request_json={},
            result_json={"stage": "queued"},
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        return job.id


def test_unsupported_job_is_failed_and_does_not_poison_queue(client: TestClient) -> None:
    project = create_project(client, "Worker poison queue")
    first_id = _queued_job(client, project["id"], "unsupported-first")
    second_id = _queued_job(client, project["id"], "unsupported-second")

    assert (
        worker.process_next_thumbnail_job(
            client.app.state.settings, client.app.state.session_factory
        )
        is True
    )
    assert (
        worker.process_next_thumbnail_job(
            client.app.state.settings, client.app.state.session_factory
        )
        is True
    )

    with client.app.state.session_factory() as session:
        first = session.get(Job, first_id)
        second = session.get(Job, second_id)
        assert first is not None
        assert second is not None
        assert first.status == "failed"
        assert second.status == "failed"
        assert first.completed_at is not None
        assert second.completed_at is not None
        assert "Unsupported queued job type" in (first.error_message or "")
        assert "Unsupported queued job type" in (second.error_message or "")


def test_unexpected_handler_error_is_contained_and_queue_continues(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = create_project(client, "Worker handler recovery")
    crashing_id = _queued_job(client, project["id"], "thumbnail")
    next_id = _queued_job(client, project["id"], "unsupported-after-crash")

    def crash(*args: object, **kwargs: object) -> bool:
        raise RuntimeError("simulated handler crash")

    monkeypatch.setattr(worker, "process_thumbnail_job", crash)

    assert (
        worker.process_next_thumbnail_job(
            client.app.state.settings, client.app.state.session_factory
        )
        is True
    )
    assert (
        worker.process_next_thumbnail_job(
            client.app.state.settings, client.app.state.session_factory
        )
        is True
    )

    with client.app.state.session_factory() as session:
        crashing = session.get(Job, crashing_id)
        following = session.get(Job, next_id)
        assert crashing is not None
        assert following is not None
        assert crashing.status == "failed"
        assert following.status == "failed"
        assert "simulated handler crash" in (crashing.error_message or "")
        assert "Unsupported queued job type" in (following.error_message or "")


def test_interrupted_video_tracking_is_not_silently_requeued(
    client: TestClient,
) -> None:
    project = create_project(client, "Interrupted tracking recovery")

    with client.app.state.session_factory() as session:
        job = Job(
            project_id=project["id"],
            job_type="video_tracking",
            status="running",
            progress_current=123,
            progress_total=300,
            request_json={"video_id": "missing-video"},
            result_json={
                "stage": "tracking",
                "frames_processed": 123,
                "detection_count": 50,
            },
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id

    recovered = worker.recover_interrupted_jobs(
        client.app.state.session_factory,
        client.app.state.settings,
    )

    assert recovered >= 1

    with client.app.state.session_factory() as session:
        job = session.get(Job, job_id)
        assert job is not None
        assert job.status == "failed"
        assert job.progress_current == 123
        assert job.progress_total == 300
        assert job.result_json["stage"] == "interrupted"
        assert job.result_json["recovery"] == "interrupted_on_startup"
        assert "123/300" in (job.error_message or "")


def test_interrupted_video_tracking_cancellation_finishes_cancelled(
    client: TestClient,
) -> None:
    project = create_project(client, "Interrupted tracking cancellation")

    with client.app.state.session_factory() as session:
        job = Job(
            project_id=project["id"],
            job_type="video_tracking",
            status="cancel_requested",
            progress_current=42,
            progress_total=300,
            request_json={"video_id": "missing-video"},
            result_json={"stage": "tracking"},
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id

    worker.recover_interrupted_jobs(
        client.app.state.session_factory,
        client.app.state.settings,
    )

    with client.app.state.session_factory() as session:
        job = session.get(Job, job_id)
        assert job is not None
        assert job.status == "cancelled"
        assert job.progress_current == 42
        assert job.result_json["stage"] == "cancelled"
        assert job.result_json["recovery"] == "interrupted_on_startup"
