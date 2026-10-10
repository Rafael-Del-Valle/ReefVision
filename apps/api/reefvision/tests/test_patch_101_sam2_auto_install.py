"""SAM 2.1 auto-managed optional checkpoint regression tests.

These tests never make network requests. Real checkpoint inference and Windows
packaging require their own acceptance runs.
"""

from __future__ import annotations

import json
from hashlib import sha256

import pytest
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.domain.errors import ValidationError
from reefvision.services.sam2_install import (
    SAM2_REPOSITORIES,
    model_directory,
    sam2_status,
    variant_repo,
)
from reefvision.tests.test_annotations import create_project


def test_sam2_catalog_contains_all_official_hiera_sizes() -> None:
    assert tuple(SAM2_REPOSITORIES) == ("tiny", "small", "base-plus", "large")
    assert variant_repo("large") == "facebook/sam2.1-hiera-large"
    with pytest.raises(ValidationError):
        variant_repo("xl")


def test_sam2_not_installed_does_not_download(tmp_path) -> None:
    status = sam2_status(Settings(data_dir=tmp_path), "large")
    assert status["installed"] is False
    assert status["ready"] is False
    assert status["revision"] is None
    assert not model_directory(Settings(data_dir=tmp_path), "large").exists()


def test_sam2_installed_provenance_is_verified(tmp_path, monkeypatch) -> None:
    settings = Settings(data_dir=tmp_path)
    target = model_directory(settings, "small")
    target.mkdir(parents=True)
    assets = {
        "config.json": b'{"model_type": "sam2"}',
        "model.safetensors": b"fixture safetensors (not executable)",
    }
    hashes = {}
    for name, data in assets.items():
        (target / name).write_bytes(data)
        hashes[name] = sha256(data).hexdigest()
    (target / ".reefvision-model.json").write_text(
        json.dumps({
            "repo_id": variant_repo("small"),
            "revision": "a" * 40,
            "files": hashes,
        }),
        encoding="utf-8",
    )
    result = sam2_status(settings, "small")
    assert result["installed"] is True
    assert result["weight_sha256"] == hashes["model.safetensors"]
    (target / "model.safetensors").write_bytes(b"tampered")
    assert sam2_status(settings, "small")["ready"] is False


def test_sam2_install_endpoint_creates_background_job_without_confirmation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = create_project(client, "SAM auto download")
    # Prevent network even if the fixture enabled the background worker.
    import reefvision.api.routes.sam2_models as routes

    monkeypatch.setattr(routes, "_launch_sam2_thread", lambda *args: None)
    response = client.post(
        f"/api/v1/projects/{project['id']}/sam2-models/large/install"
    )
    assert response.status_code == 200, response.text
    job = response.json()
    assert job["job_type"] == "sam2_install"
    assert job["request_json"]["variant"] == "large"
    assert job["request_json"]["auto_install_on_model_selection"] is True
