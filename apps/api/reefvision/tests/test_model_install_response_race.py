from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from reefvision.db.models import Job
from reefvision.schemas.model_catalog import CatalogExpectedFile, ModelCatalogEntryResponse
from reefvision.services.model_catalog import ModelCatalogService
from reefvision.tests.test_annotations import create_project


def _entry(payload: bytes) -> ModelCatalogEntryResponse:
    from reefvision.services.model_catalog import _load_static_model_catalog

    original = next(
        item
        for item in _load_static_model_catalog().models
        if item.catalog_id == "ultralytics/yolo11/detect/n"
    )
    digest = hashlib.sha256(payload).hexdigest()
    expected = CatalogExpectedFile(
        filename="yolo11n.pt",
        source_url="https://example.invalid/yolo11n.pt",
        revision="response-race-test",
        sha256=digest,
        size_bytes=len(payload),
    )
    return original.model_copy(
        update={
            "expected_files": [expected],
            "expected_size": len(payload),
            "expected_checksum": digest,
            "expected_file_size": len(payload),
            "installation_state": "Not Installed",
            "installation_reason": "Test checkpoint is not installed.",
        }
    )


def test_install_response_is_frozen_before_background_start(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = _entry(b"response-race")
    monkeypatch.setattr(
        ModelCatalogService,
        "get_static_catalog_item",
        lambda self, catalog_id: entry,
    )
    monkeypatch.setattr(client.app.state.settings, "background_worker_enabled", True)

    started: list[str] = []

    def mutate_job_immediately(settings: object, factory: object, job_id: str) -> None:
        started.append(job_id)
        with client.app.state.session_factory() as session:
            job = session.get(Job, job_id)
            assert job is not None
            job.status = "running"
            session.commit()

    monkeypatch.setattr(
        "reefvision.api.routes.model_catalog._start_model_install_thread",
        mutate_job_immediately,
    )

    project = create_project(client, "Install response race")
    endpoint = f"/api/v1/projects/{project['id']}/model-installs/ultralytics%2Fyolo11%2Fdetect%2Fn"

    response = client.post(endpoint, json={"confirmed": True})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "queued"
    assert started == [payload["id"]]

    with client.app.state.session_factory() as session:
        persisted = session.get(Job, payload["id"])
        assert persisted is not None
        assert persisted.status == "running"
