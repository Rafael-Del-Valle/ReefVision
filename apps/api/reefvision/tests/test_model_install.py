from __future__ import annotations

import hashlib
import io

import pytest
from fastapi.testclient import TestClient

from reefvision.db.models import Job
from reefvision.jobs.model_install import process_model_install_job
from reefvision.schemas.model_catalog import CatalogExpectedFile, ModelCatalogEntryResponse
from reefvision.services.model_catalog import ModelCatalogService
from reefvision.storage.catalog_models import (
    catalog_asset_path,
    catalog_manifest_record,
    load_catalog_manifest,
)
from reefvision.tests.test_annotations import create_project


class FakeDownload(io.BytesIO):
    def __enter__(self) -> FakeDownload:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def _mini_entry(payload: bytes) -> ModelCatalogEntryResponse:
    from reefvision.services.model_catalog import _load_static_model_catalog

    original = next(
        item
        for item in _load_static_model_catalog().models
        if item.catalog_id == "ultralytics/yolo11/detect/n"
    )
    sha256 = hashlib.sha256(payload).hexdigest()
    expected = CatalogExpectedFile(
        filename="yolo11n.pt",
        source_url=("https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt"),
        revision="test-v8.3.0",
        sha256=sha256,
        size_bytes=len(payload),
    )
    return original.model_copy(
        update={
            "expected_files": [expected],
            "expected_size": len(payload),
            "expected_checksum": sha256,
            "expected_file_size": len(payload),
            "installation_state": "Not Installed",
            "installation_reason": "Test checkpoint is not installed.",
        }
    )


def _patch_entry(monkeypatch: pytest.MonkeyPatch, entry: ModelCatalogEntryResponse) -> None:
    monkeypatch.setattr(
        ModelCatalogService,
        "get_static_catalog_item",
        lambda self, catalog_id: entry,
    )
    monkeypatch.setattr(
        ModelCatalogService,
        "get_project_catalog_item",
        lambda self, project_id, catalog_id: self._compose_static_state(
            entry,
            job=self._latest_install_jobs(project_id).get(entry.catalog_id),
            manifest=load_catalog_manifest(self.settings),
        ),
    )


def test_install_requires_confirmation_and_creates_background_job(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _mini_entry(b"trusted-checkpoint")
    _patch_entry(monkeypatch, entry)
    project = create_project(client, "Install confirmation")
    endpoint = f"/api/v1/projects/{project['id']}/model-installs/ultralytics%2Fyolo11%2Fdetect%2Fn"

    rejected = client.post(endpoint, json={"confirmed": False})
    accepted = client.post(endpoint, json={"confirmed": True})

    assert rejected.status_code == 400
    assert accepted.status_code == 200, accepted.text
    job = accepted.json()
    assert job["job_type"] == "model_install"
    assert job["status"] == "queued"
    assert job["request_json"]["catalog_id"] == entry.catalog_id


def test_successful_install_verifies_persists_and_can_be_removed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"trusted-checkpoint-for-offline-use"
    entry = _mini_entry(payload)
    _patch_entry(monkeypatch, entry)
    monkeypatch.setattr(
        "reefvision.jobs.model_install.urllib.request.urlopen",
        lambda *args, **kwargs: FakeDownload(payload),
    )
    project = create_project(client, "Managed install")
    endpoint = f"/api/v1/projects/{project['id']}/model-installs/ultralytics%2Fyolo11%2Fdetect%2Fn"
    response = client.post(endpoint, json={"confirmed": True})
    assert response.status_code == 200, response.text
    job_id = response.json()["id"]

    processed = process_model_install_job(
        client.app.state.settings,
        client.app.state.session_factory,
        job_id,
    )

    assert processed is True
    with client.app.state.session_factory() as session:
        job = session.get(Job, job_id)
        assert job is not None
        assert job.status == "succeeded"
        assert job.progress_current == len(payload)
        assert job.result_json["sha256"] == hashlib.sha256(payload).hexdigest()
        service = ModelCatalogService(session, client.app.state.settings)
        state = service._compose_static_state(
            entry,
            job=service._latest_install_jobs(project["id"]).get(entry.catalog_id),
            manifest=load_catalog_manifest(client.app.state.settings),
        )
        assert state.installation_state == "Ready"
        assert state.installed_asset_id == f"catalog_model:{entry.catalog_id}"
    record = catalog_manifest_record(client.app.state.settings, entry.catalog_id)
    assert record is not None
    assert record["sha256"] == hashlib.sha256(payload).hexdigest()

    verify_response = client.post(
        f"/api/v1/projects/{project['id']}/model-verifications/ultralytics%2Fyolo11%2Fdetect%2Fn"
    )
    assert verify_response.status_code == 200
    assert verify_response.json()["verified"] is True

    remove_response = client.delete(endpoint)
    assert remove_response.status_code == 204
    path = catalog_asset_path(
        client.app.state.settings, entry.catalog_id, entry.expected_files[0].filename
    )
    assert not path.exists()
    assert catalog_manifest_record(client.app.state.settings, entry.catalog_id) is None


def test_corrupt_download_is_rejected(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    entry = _mini_entry(b"expected")
    _patch_entry(monkeypatch, entry)
    monkeypatch.setattr(
        "reefvision.jobs.model_install.urllib.request.urlopen",
        lambda *args, **kwargs: FakeDownload(b"corrupt!"),
    )
    project = create_project(client, "Corrupt install")
    endpoint = f"/api/v1/projects/{project['id']}/model-installs/ultralytics%2Fyolo11%2Fdetect%2Fn"
    job_id = client.post(endpoint, json={"confirmed": True}).json()["id"]

    assert (
        process_model_install_job(
            client.app.state.settings, client.app.state.session_factory, job_id
        )
        is False
    )
    with client.app.state.session_factory() as session:
        job = session.get(Job, job_id)
        assert job is not None
        assert job.status == "failed"
        assert "Checksum mismatch" in (job.error_message or "")
    path = catalog_asset_path(
        client.app.state.settings, entry.catalog_id, entry.expected_files[0].filename
    )
    assert not path.exists()


def test_install_job_cancellation_is_persistent(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _mini_entry(b"cancelled")
    _patch_entry(monkeypatch, entry)
    project = create_project(client, "Cancelled install")
    endpoint = f"/api/v1/projects/{project['id']}/model-installs/ultralytics%2Fyolo11%2Fdetect%2Fn"
    job = client.post(endpoint, json={"confirmed": True}).json()

    response = client.post(f"/api/v1/jobs/{job['id']}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert response.json()["completed_at"] is not None
    assert (
        process_model_install_job(
            client.app.state.settings, client.app.state.session_factory, job["id"]
        )
        is False
    )


def test_ready_catalog_model_resolves_training_provenance(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"training-seed"
    entry = _mini_entry(payload)
    _patch_entry(monkeypatch, entry)
    project = create_project(client, "Training provenance")
    expected = entry.expected_files[0]
    path = catalog_asset_path(client.app.state.settings, entry.catalog_id, expected.filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    from reefvision.storage.catalog_models import write_catalog_manifest_record

    write_catalog_manifest_record(
        client.app.state.settings,
        entry.catalog_id,
        {
            "filename": expected.filename,
            "relative_path": path.relative_to(
                client.app.state.settings.resolved_data_dir
            ).as_posix(),
            "sha256": expected.sha256,
            "size_bytes": expected.size_bytes,
        },
    )
    with client.app.state.session_factory() as session:
        selection = ModelCatalogService(
            session, client.app.state.settings
        ).resolve_training_selection(project["id"], entry.catalog_id)

    assert selection.initial_checkpoint_source == "managed_catalog"
    assert selection.resolved_model_asset_id == f"catalog_model:{entry.catalog_id}"
    assert selection.resolved_model_checksum == expected.sha256


def test_install_is_rejected_in_safe_mode(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = _mini_entry(b"safe-mode-checkpoint")
    _patch_entry(monkeypatch, entry)
    monkeypatch.setattr(client.app.state.settings, "safe_mode", True)

    project = create_project(client, "Safe mode install")
    endpoint = f"/api/v1/projects/{project['id']}/model-installs/ultralytics%2Fyolo11%2Fdetect%2Fn"

    response = client.post(endpoint, json={"confirmed": True})

    assert response.status_code == 409
    assert "Safe Mode" in response.json()["detail"]

def test_job_status_response_disables_http_caching(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _mini_entry(b"live-progress")
    _patch_entry(monkeypatch, entry)
    project = create_project(client, "Live install progress")
    endpoint = f"/api/v1/projects/{project['id']}/model-installs/ultralytics%2Fyolo11%2Fdetect%2Fn"
    created = client.post(endpoint, json={"confirmed": True})
    assert created.status_code == 200, created.text

    response = client.get(f"/api/v1/jobs/{created.json()['id']}?poll=1")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["expires"] == "0"

