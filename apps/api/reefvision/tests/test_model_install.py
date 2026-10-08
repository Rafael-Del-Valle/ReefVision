"""Retired catalog acquisition must fail closed and preserve researchers' files."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import Job
from reefvision.jobs.model_install import process_model_install_job
from reefvision.services.model_catalog import ModelCatalogService
from reefvision.tests.test_annotations import create_project


@pytest.mark.parametrize("confirmed", [True, False])
@pytest.mark.parametrize("safe_mode", [True, False])
def test_legacy_install_request_never_queues_job(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, confirmed: bool, safe_mode: bool
) -> None:
    project = create_project(client, "No model acquisition")
    app = cast(FastAPI, client.app)
    monkeypatch.setattr(app.state.settings, "safe_mode", safe_mode)
    response = client.post(
        f"/api/v1/projects/{project['id']}/model-installs/ultralytics/yolo11/detect/n",
        json={"confirmed": confirmed},
    )
    assert response.status_code == 400
    assert "register" in response.text
    with app.state.session_factory() as session:
        assert list(session.scalars(select(Job).where(Job.job_type == "model_install"))) == []


@pytest.mark.parametrize("job_status", ["queued", "running", "succeeded", "cancel_requested"])
def test_legacy_worker_retires_only_queued_jobs_without_mutating_assets(
    client: TestClient, job_status: str, tmp_path: Path
) -> None:
    project = create_project(client, "Legacy upgrade")
    app = cast(FastAPI, client.app)
    local_model = tmp_path / "researcher.pt"
    local_model.write_bytes(b"user-file-do-not-modify")
    with app.state.session_factory() as session:
        job = Job(
            project_id=project["id"],
            job_type="model_install",
            status=job_status,
            request_json={"catalog_id": "ultralytics/yolo11/detect/n"},
            result_json={"original": "retained until retirement"},
        )
        session.add(job)
        session.commit()
        job_id = job.id
    changed = process_model_install_job(app.state.settings, app.state.session_factory, job_id)
    assert changed is (job_status == "queued")
    with app.state.session_factory() as session:
        persisted = session.get(Job, job_id)
        assert persisted is not None
        assert persisted.status == ("failed" if job_status == "queued" else job_status)
        if job_status == "queued":
            assert persisted.completed_at is not None
            assert "register" in str(persisted.error_message)
    assert local_model.read_bytes() == b"user-file-do-not-modify"
    assert not process_model_install_job(app.state.settings, app.state.session_factory, job_id)


def test_architecture_resolves_random_training_without_checksum(client: TestClient) -> None:
    project = create_project(client, "Random initialization")
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        result = ModelCatalogService(session, app.state.settings).resolve_training_selection(
            project["id"], "ultralytics/yolo11/detect/n"
        )
    assert result.initial_checkpoint_source == "scratch"
    assert result.initial_checkpoint_model_id is None
    assert result.resolved_model_checksum is None
    assert result.architecture == "yolo11n.yaml"


def test_catalog_removal_cannot_delete_uncertain_legacy_assets(client: TestClient) -> None:
    project = create_project(client, "Protect models")
    app = cast(FastAPI, client.app)
    root = app.state.settings.resolved_data_dir / "provider-models" / "grounding_dino"
    root.mkdir(parents=True)
    weight = root / "model.safetensors"
    weight.write_bytes(b"researcher model")
    response = client.delete(
        f"/api/v1/projects/{project['id']}/model-installs/transformers/grounding_dino/tiny"
    )
    assert response.status_code == 400
    assert weight.read_bytes() == b"researcher model"
