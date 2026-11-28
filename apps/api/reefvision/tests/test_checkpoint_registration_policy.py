from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import TrainingRun
from reefvision.domain.errors import ValidationError
from reefvision.jobs.inference import process_inference_job
from reefvision.jobs.project_exchange import process_project_exchange_export_job
from reefvision.jobs.training import _resolve_model_source
from reefvision.services.models import ModelService
from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_model_inference import FakeDetectorRegistrationProvider, register_model


@pytest.mark.parametrize(
    ("policy", "approved", "expected"),
    [(None, False, 400), (None, True, 200), (False, True, 400), (True, False, 200)],
)
def test_local_checkpoint_approval(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    policy: bool | None,
    approved: bool,
    expected: int,
) -> None:
    app = cast(FastAPI, client.app)
    app.state.settings.allow_unsafe_pickled_models = policy
    project = create_project(client, "Local model registration")
    monkeypatch.setattr(
        ModelService, "_provider_for_purpose", lambda *_: FakeDetectorRegistrationProvider()
    )
    response = client.post(
        f"/api/v1/projects/{project['id']}/models/register",
        data={"purpose": "detector", "trust_checkpoint": str(approved).lower()},
        files={"file": ("best.pt", b"fixture-only", "application/octet-stream")},
    )
    assert response.status_code == expected, response.text
    rows = client.get(f"/api/v1/projects/{project['id']}/models").json()
    if expected == 200:
        assert len(rows) == 1
        if approved:
            assert rows[0]["metadata_json"]["checkpoint_trust"]["sha256"] == rows[0]["sha256"]
    else:
        assert rows == []


def test_strict_policy_rejects_pickle_members_in_transformers_archive(client: TestClient) -> None:
    app = cast(FastAPI, client.app)
    app.state.settings.allow_unsafe_pickled_models = False
    project = create_project(client, "Transformer registration")
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("config.json", '{"model_type":"sam2"}')
        archive.writestr("preprocessor_config.json", "{}")
        archive.writestr("pytorch_model.bin", b"fixture-only")
    response = client.post(
        f"/api/v1/projects/{project['id']}/models/register",
        data={"purpose": "assist", "provider_name": "sam2", "trust_checkpoint": "true"},
        files={"file": ("sam2.zip", stream.getvalue(), "application/zip")},
    )
    assert response.status_code == 400, response.text
    assert "disabled" in response.json()["detail"]


def test_exchange_model_needs_new_local_execution_approval(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:

    app = cast(FastAPI, client.app)
    project = create_project(client, "Local source")
    monkeypatch.setattr(
        ModelService, "_provider_for_purpose", lambda *_: FakeDetectorRegistrationProvider()
    )
    original = register_model(
        client,
        project["id"],
        purpose="detector",
        filename="best.pt",
        display_name="Known checkpoint",
    )
    queued = client.post(
        f"/api/v1/projects/{project['id']}/exchange-packages",
        json={"include_model_weights": True, "include_media": False},
    )
    assert queued.status_code == 202, queued.text
    package = queued.json()
    assert process_project_exchange_export_job(
        app.state.settings, app.state.session_factory, package["job_id"]
    )
    downloaded = client.get(f"/api/v1/exchange-packages/{package['package']['id']}/download")
    assert downloaded.status_code == 200
    restored = client.post(
        "/api/v1/exchange-packages/import",
        files={"file": ("project.reefvision.zip", downloaded.content, "application/zip")},
    )
    assert restored.status_code == 201, restored.text
    project_id = restored.json()["project_id"]
    [historical] = client.get(f"/api/v1/projects/{project_id}/models").json()
    assert historical["sha256"] == original["sha256"]
    assert historical["metadata_json"] == original["metadata_json"]
    image_id = import_one(client, project_id)["successful"][0]["image_id"]
    endpoint = f"/api/v1/projects/{project_id}/inference-jobs"
    request = {"model_id": historical["id"], "image_ids": [image_id], "device": "cpu"}
    refused = client.post(endpoint, json=request)
    assert refused.status_code == 400, refused.text
    assert "approve" in refused.json()["detail"].lower()

    seed = TrainingRun(
        project_id=project_id,
        task="detect",
        initial_checkpoint_source="registered_model",
        initial_checkpoint_model_id=historical["id"],
        resolved_model_checksum=historical["sha256"],
    )
    with app.state.session_factory() as session, pytest.raises(ValidationError, match="Approve"):
        _resolve_model_source(app.state.settings, session, seed)

    approve = f"/api/v1/projects/{project_id}/models/{historical['id']}/approve-checkpoint"
    assert client.post(approve, json={"sha256": "a" * 64}).status_code == 409
    assert client.post(approve, json={"sha256": historical["sha256"]}).status_code == 200
    queued_job = client.post(endpoint, json=request)
    assert queued_job.status_code == 200
    with app.state.session_factory() as session:
        path = _resolve_model_source(app.state.settings, session, seed)
        assert Path(path).read_bytes() == b"fixture-model"
    app.state.settings.allow_unsafe_pickled_models = False
    assert client.post(endpoint, json=request).status_code == 400

    assert not process_inference_job(
        app.state.settings, app.state.session_factory, queued_job.json()["id"]
    )
    blocked_job = client.get(f"/api/v1/jobs/{queued_job.json()['id']}").json()
    assert blocked_job["status"] == "failed" and "disabled" in blocked_job["error_message"]
