from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from reefvision.config import Settings
from reefvision.db.models import BackupRecord, Job
from reefvision.jobs.backups import process_backup_job
from reefvision.jobs.worker import process_thumbnail_job

from .test_images import create_project, import_one


def create_completed_backup(
    client: TestClient,
    test_settings: Settings,
) -> tuple[dict[str, Any], dict[str, Any]]:
    project = create_project(client, "Backup project")
    import_report = import_one(client, project["id"])
    image_item = import_report["successful"][0]
    app = cast(FastAPI, client.app)
    factory = app.state.session_factory
    assert process_thumbnail_job(test_settings, factory, image_item["thumbnail_job_id"])

    logs_dir = test_settings.resolved_data_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / "desktop.log").write_text("desktop log\n", encoding="utf-8")

    create_response = client.post(
        "/api/v1/backups",
        json={"notes": "Milestone 8 test backup", "include_exports": False, "include_logs": False},
    )
    assert create_response.status_code == 201, create_response.text
    payload = cast(dict[str, Any], create_response.json())
    assert process_backup_job(test_settings, factory, payload["job"]["id"])
    backup = client.get(f"/api/v1/backups/{payload['backup']['id']}").json()
    return payload, cast(dict[str, Any], backup)


def test_backup_job_parent_is_persisted_before_fk_constrained_backup_record(
    client: TestClient, test_settings: Settings
) -> None:
    """An actual backup job must survive with SQLite FK checks enabled."""
    created, backup = create_completed_backup(client, test_settings)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        assert session.scalar(text("PRAGMA foreign_keys")) == 1
        assert session.scalar(text("PRAGMA foreign_key_check")) is None
        job = session.get(Job, created["job"]["id"])
        record = session.get(BackupRecord, backup["id"])
        assert job is not None
        assert record is not None
        assert job.job_type == "backup"
        assert record.job_id == job.id
        assert job.status == "completed"
        assert record.status == "completed"


def test_backup_job_creates_verified_managed_backup(
    client: TestClient, test_settings: Settings
) -> None:
    created, backup = create_completed_backup(client, test_settings)

    assert backup["status"] == "completed"
    assert backup["job_id"] == created["job"]["id"]
    manifest_path = test_settings.resolved_data_dir / Path(backup["manifest_path"])
    completion_path = test_settings.resolved_data_dir / Path(backup["completion_marker_path"])
    assert manifest_path.is_file()
    assert completion_path.is_file()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["backup_id"] == backup["id"]
    assert manifest["database_filename"] == "test.db"
    assert manifest["included_sections"] == ["database", "models", "projects", "thumbnails"]
    assert "logs" in manifest["excluded_sections"]
    inventory_paths = {item["path"] for item in manifest["file_inventory"]}
    assert "database/test.db" in inventory_paths
    assert not any(path.startswith("data/logs/") for path in inventory_paths)
    assert any(path.endswith(".jpg") for path in inventory_paths)

    verify_response = client.post(f"/api/v1/backups/{backup['id']}/verify")
    assert verify_response.status_code == 200
    verification = verify_response.json()
    assert verification["status"] == "valid"
    assert verification["completion_marker_present"] is True
    assert not verification["errors"]
    assert not verification["checksum_failures"]


def test_backup_verification_rejects_missing_completion_marker(
    client: TestClient, test_settings: Settings
) -> None:
    _, backup = create_completed_backup(client, test_settings)
    completion_path = test_settings.resolved_data_dir / Path(backup["completion_marker_path"])
    completion_path.unlink()

    verify_response = client.post(f"/api/v1/backups/{backup['id']}/verify")
    assert verify_response.status_code == 200
    verification = verify_response.json()
    assert verification["status"] == "invalid"
    assert verification["completion_marker_present"] is False
    assert any("completion marker" in message.lower() for message in verification["errors"])


def test_backup_verification_rejects_checksum_change(
    client: TestClient, test_settings: Settings
) -> None:
    _, backup = create_completed_backup(client, test_settings)
    manifest_path = test_settings.resolved_data_dir / Path(backup["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    changed_entry = next(
        item for item in manifest["file_inventory"] if item["path"].startswith("data/projects/")
    )
    changed_path = (
        test_settings.resolved_data_dir
        / Path(backup["destination_path"])
        / Path(changed_entry["path"])
    )
    changed_path.write_bytes(changed_path.read_bytes() + b"tamper")

    verify_response = client.post(f"/api/v1/backups/{backup['id']}/verify")
    assert verify_response.status_code == 200
    verification = verify_response.json()
    assert verification["status"] == "invalid"
    assert changed_entry["path"] in verification["checksum_failures"]


def test_cancelled_queued_backup_does_not_create_valid_directory(
    client: TestClient, test_settings: Settings
) -> None:
    project = create_project(client, "Cancelled backup project")
    report = import_one(client, project["id"])
    app = cast(FastAPI, client.app)
    factory = app.state.session_factory
    assert process_thumbnail_job(
        test_settings, factory, report["successful"][0]["thumbnail_job_id"]
    )

    create_response = client.post("/api/v1/backups", json={})
    assert create_response.status_code == 201
    created = create_response.json()

    cancel_response = client.post(f"/api/v1/jobs/{created['job']['id']}/cancel")
    assert cancel_response.status_code == 200
    backup = client.get(f"/api/v1/backups/{created['backup']['id']}").json()
    assert backup["status"] == "cancelled"
    assert not (test_settings.resolved_data_dir / Path(backup["destination_path"])).exists()
