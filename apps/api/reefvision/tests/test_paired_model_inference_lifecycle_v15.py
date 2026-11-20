"""Comparisons own their evaluation-only children through restart and cancellation."""

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import Job, PredictionProposal
from reefvision.domain.errors import ConflictError
from reefvision.repositories.jobs import JobRepository
from reefvision.services import model_comparison_stills_v15 as stills
from reefvision.tests.test_model_comparison_stills_v15 import _confirm_runtime, _dataset, _register
from reefvision.tests.test_model_comparison_stills_v15 import (
    reviewed_runtime as reviewed_runtime_fixture,
)

reviewed_runtime = reviewed_runtime_fixture


def _inputs(client: TestClient) -> tuple[FastAPI, str, str, str, list[dict[str, Any]]]:
    app = cast(FastAPI, client.app)
    project, cls, _, version = _dataset(client)
    models = [
        _register(client, project, version, cls, "detect", side) for side in ("left", "right")
    ]
    selections = [_confirm_runtime(client, project, model) for model in models]
    with app.state.session_factory() as session:
        owner = Job(project_id=project, job_type="paired_model_comparison", status="running")
        session.add(owner)
        session.commit()
        return app, project, version["id"], owner.id, selections


def test_restart_reuses_the_completed_side_and_excludes_owned_jobs_from_general_pickup(
    client: TestClient,
    reviewed_runtime: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, project, dataset, owner, selections = _inputs(client)
    executed = []
    processor = stills.process_inference_job

    def interrupt(settings: Any, factory: Any, job_id: str) -> bool:
        with factory() as session:
            child = session.get(Job, job_id)
            assert child.request_json["paired_owner_run_id"] == owner
            ordinary = JobRepository(session).next_queued()
            assert ordinary is None or ordinary.id != job_id
        outcome = processor(settings, factory, job_id)
        executed.append(job_id)
        if len(executed) == 1:
            raise RuntimeError("Simulated process interruption")
        return outcome

    monkeypatch.setattr(stills, "process_inference_job", interrupt)

    def compare() -> dict[str, Any]:
        with app.state.session_factory() as session:
            return stills.compare_image_models(
                session,
                app.state.settings,
                project,
                "detector",
                {"dataset_version_id": dataset},
                selections,
                owner_run_id=owner,
            )

    with pytest.raises(RuntimeError, match="interruption"):
        compare()
    with app.state.session_factory() as session:
        JobRepository(session).recover_interrupted_jobs()
        row = session.get(Job, owner)
        assert row.status == "queued"
        row.status = "running"
        session.commit()
    result = compare()
    assert result["inference_job_ids"] == executed
    assert len(executed) == 2
    with app.state.session_factory() as session:
        children = session.scalars(select(Job).where(Job.job_type == "inference")).all()
        assert len(children) == 2 and all(row.status == "succeeded" for row in children)
        assert set(session.scalars(select(PredictionProposal.review_status))) == {"evaluation_only"}


def test_parent_cancellation_stops_before_second_side_and_restart_cleans_an_orphan(
    client: TestClient,
    reviewed_runtime: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, project, dataset, owner, selections = _inputs(client)
    processor = stills.process_inference_job

    def stop_after_first(settings: Any, factory: Any, job_id: str) -> bool:
        result = processor(settings, factory, job_id)
        with factory() as session:
            session.get(Job, owner).status = "cancel_requested"
            session.commit()
        return result

    monkeypatch.setattr(stills, "process_inference_job", stop_after_first)
    with app.state.session_factory() as session, pytest.raises(ConflictError, match="stopped"):
        stills.compare_image_models(
            session,
            app.state.settings,
            project,
            "detector",
            {"dataset_version_id": dataset},
            selections,
            owner_run_id=owner,
        )
    with app.state.session_factory() as session:
        [completed] = session.scalars(select(Job).where(Job.job_type == "inference")).all()
        assert completed.status == "succeeded"
        orphan = Job(
            job_type="inference",
            status="queued",
            project_id=project,
            request_json={"paired_owner_run_id": owner, "evaluation_only": True},
        )
        session.add(orphan)
        session.flush()
        JobRepository(session).recover_interrupted_jobs()
        assert orphan.status == "cancelled"
        assert session.get(Job, owner).status == "cancelled"
