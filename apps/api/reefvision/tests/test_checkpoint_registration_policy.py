from __future__ import annotations

import io
import zipfile
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.services.models import ModelService
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_model_inference import FakeDetectorRegistrationProvider


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
