from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision import __version__
from reefvision.config import Settings
from reefvision.jobs.diagnostics import process_diagnostics_job
from reefvision.jobs.restores import process_restore_job
from reefvision.storage.backups import BACKUP_FORMAT_VERSION

from .test_backups import create_completed_backup


def test_restore_job_restores_backup_into_new_recovery_location(
    client: TestClient,
    test_settings: Settings,
) -> None:
    _, backup = create_completed_backup(client, test_settings)
    app = cast(FastAPI, client.app)
    factory = app.state.session_factory

    restore_response = client.post(
        f"/api/v1/backups/{backup['id']}/restore",
        json={"destination_name": "recovery-copy"},
    )

    assert restore_response.status_code == 200, restore_response.text
    restore_payload = cast(dict[str, Any], restore_response.json())
    assert process_restore_job(test_settings, factory, restore_payload["job"]["id"])

    job_response = client.get(f"/api/v1/jobs/{restore_payload['job']['id']}")
    assert job_response.status_code == 200
    job = cast(dict[str, Any], job_response.json())
    assert job["status"] == "succeeded"
    assert job["result_json"]["destination_path"] == "recoveries/recovery-copy"

    restore_root = test_settings.resolved_data_dir / "recoveries" / "recovery-copy"
    assert (restore_root / "restore-receipt.json").is_file()
    assert (restore_root / "restored-from-backup-complete.json").is_file()
    assert any(path.is_file() for path in restore_root.rglob("*.jpg"))
    assert any(path.is_file() for path in restore_root.rglob("*.db"))


def test_restore_rejects_existing_destination(
    client: TestClient,
    test_settings: Settings,
) -> None:
    _, backup = create_completed_backup(client, test_settings)
    existing = test_settings.resolved_data_dir / "recoveries" / "collision"
    existing.mkdir(parents=True, exist_ok=True)

    restore_response = client.post(
        f"/api/v1/backups/{backup['id']}/restore",
        json={"destination_name": "collision"},
    )

    assert restore_response.status_code == 409
    assert "already exists" in restore_response.json()["detail"]


def test_diagnostics_job_creates_redacted_bundle(
    client: TestClient,
    test_settings: Settings,
) -> None:
    logs_dir = test_settings.resolved_data_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    secret_path = str(Path.home() / "reefvision-secret-notes")
    (logs_dir / "desktop.log").write_text(
        f"developer path {secret_path}\nmanaged {test_settings.resolved_data_dir}\n",
        encoding="utf-8",
    )

    create_response = client.post(
        "/api/v1/system/diagnostics",
        json={"strict_redaction": True},
    )
    assert create_response.status_code == 200, create_response.text
    payload = cast(dict[str, Any], create_response.json())

    app = cast(FastAPI, client.app)
    factory = app.state.session_factory
    assert process_diagnostics_job(test_settings, factory, payload["job"]["id"])

    status_response = client.get(f"/api/v1/system/diagnostics/{payload['job']['id']}")
    assert status_response.status_code == 200
    status_payload = cast(dict[str, Any], status_response.json())
    assert status_payload["job"]["status"] == "succeeded"
    assert status_payload["diagnostic_bundle_version"] is not None

    bundle_relative = cast(str, status_payload["bundle_path"])
    bundle_path = test_settings.resolved_data_dir / Path(bundle_relative)
    assert bundle_path.is_file()

    with zipfile.ZipFile(bundle_path, mode="r") as archive:
        assert "diagnostic-bundle.json" in archive.namelist()
        assert all(
            not name.lower().endswith((".jpg", ".png", ".tif", ".webp"))
            for name in archive.namelist()
        )
        payload_json = json.loads(archive.read("diagnostic-bundle.json").decode("utf-8"))
        log_text = archive.read("logs/desktop.log").decode("utf-8")

    assert payload_json["reefvision_application_version"] == __version__
    assert payload_json["backup_format_version"] == BACKUP_FORMAT_VERSION
    assert payload_json["paths"]["data_dir"] == "%REEFVISION_DATA_DIR%"
    assert str(Path.home()) not in log_text
    assert "%USER_HOME%" in log_text or "<user>" in log_text
