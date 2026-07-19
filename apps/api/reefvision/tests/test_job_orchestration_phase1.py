from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from reefvision.db.models import Job, Project
from reefvision.domain.errors import ConflictError, ValidationError
from reefvision.services.job_orchestration import JobOrchestrationService


def test_job_dependencies_transitions_heartbeats_and_checkpoint_retry(
    client: TestClient,
) -> None:
    with client.app.state.session_factory() as session:
        project = Project(
            name="Synthetic orchestration",
            slug="synthetic-orchestration",
            storage_root="projects/synthetic-orchestration",
        )
        session.add(project)
        session.flush()
        upstream = Job(
            project_id=project.id,
            job_type="export",
            status="queued",
            max_retries=1,
        )
        downstream = Job(
            project_id=project.id,
            job_type="workflow_run",
            status="queued",
            max_retries=2,
            resume_supported=True,
        )
        session.add_all([upstream, downstream])
        session.commit()
        service = JobOrchestrationService(session)

        service.add_dependency(downstream.id, upstream.id)
        assert service.refresh_blocked_state(downstream.id).status == "blocked"
        service.transition(upstream.id, "running")
        service.heartbeat(
            upstream.id,
            worker_id="worker-a",
            progress_current=1,
            progress_total=2,
        )
        service.transition(upstream.id, "succeeded")
        assert service.refresh_blocked_state(downstream.id).status == "queued"

        service.transition(downstream.id, "running")
        service.heartbeat(
            downstream.id,
            worker_id="worker-b",
            progress_current=3,
            progress_total=10,
            checkpoint={"last_node": "segment"},
        )
        service.transition(downstream.id, "failed", message="synthetic interruption")
        retried = service.retry(downstream.id, from_checkpoint=True)
        assert retried.status == "queued"
        assert retried.retry_count == 1
        assert retried.checkpoint_json == {"last_node": "segment"}
        assert len(service.events(downstream.id)) >= 4

        service.transition(downstream.id, "running")
        service.transition(downstream.id, "succeeded")
        with pytest.raises(ConflictError, match="Invalid job transition"):
            service.transition(downstream.id, "running")


def test_job_dependencies_reject_cycles(client: TestClient) -> None:
    with client.app.state.session_factory() as session:
        project = Project(
            name="Cycle project",
            slug="cycle-project",
            storage_root="projects/cycle-project",
        )
        session.add(project)
        session.flush()
        first = Job(project_id=project.id, job_type="export")
        second = Job(project_id=project.id, job_type="export")
        session.add_all([first, second])
        session.commit()
        service = JobOrchestrationService(session)
        service.add_dependency(first.id, second.id)
        with pytest.raises(ValidationError, match="cycle"):
            service.add_dependency(second.id, first.id)
