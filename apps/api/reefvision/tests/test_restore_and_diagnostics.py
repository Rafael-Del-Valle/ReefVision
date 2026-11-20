from __future__ import annotations

import json
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision import __version__
from reefvision.config import Settings
from reefvision.jobs import restores
from reefvision.jobs.backups import process_backup_job
from reefvision.jobs.diagnostics import process_diagnostics_job
from reefvision.jobs.restores import process_restore_job
from reefvision.storage.backups import BACKUP_FORMAT_VERSION, backup_io_path

from .test_backups import create_completed_backup
from .test_images import create_project


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


def test_restore_keeps_preexisting_marker_and_receipt_named_directory(
    client: TestClient, test_settings: Settings
) -> None:
    root = test_settings.resolved_data_dir
    root.mkdir(parents=True, exist_ok=True)
    marker = root / "restored-from-backup-complete.json"
    marker.write_bytes(b"original field recovery log")
    directory = root / "Restore-Receipt-2.json"
    directory.mkdir()
    (directory / "notes").write_bytes(b"retained field notes")
    _, backup = create_completed_backup(client, test_settings)
    response = (
        client.post(
            f"/api/v1/backups/{backup['id']}/restore", json={"destination_name": "retained-history"}
        )
        .raise_for_status()
        .json()
    )
    job_id = response["job"]["id"]
    assert process_restore_job(
        test_settings, cast(FastAPI, client.app).state.session_factory, job_id
    )
    target = root / response["destination_path"]
    result = client.get(f"/api/v1/jobs/{job_id}").raise_for_status().json()["result_json"]
    assert (target / marker.name).read_bytes() == marker.read_bytes()
    assert (target / directory.name / "notes").read_bytes() == b"retained field notes"
    assert result["restore_receipt_filename"] == "restore-receipt-3.json"
    assert result["completion_marker_filename"] == "restored-from-backup-complete-3.json"
    assert (
        json.loads((target / result["restore_receipt_filename"]).read_bytes())["restore_job_id"]
        == job_id
    )
    assert (target / result["completion_marker_filename"]).read_bytes() == (
        root / backup["completion_marker_path"]
    ).read_bytes()


@pytest.mark.parametrize(
    ("destination_name", "published_length"),
    [("archive1", 256), ("backup-copy-17545a73-20b", 256), ("backup-copy-17545a73-20b", 261)],
)
def test_restore_reads_published_members_near_windows_path_limit(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    destination_name: str,
    published_length: int,
) -> None:
    project = create_project(client, "Recovery path-length fixture")
    captured_root = test_settings.resolved_data_dir
    root = captured_root.with_name(captured_root.name + "-restore-target")
    project_path = Path(str(project["storage_root"]))
    target = root / "recoveries" / destination_name
    # Keep room for the deliberate padding under the default Windows pytest directory.
    member = project_path / "training" / "dataset" / "weights.bin"
    padding = published_length - len(str(target / member)) - 1
    assert 0 < padding < 255
    member = member.parent / ("x" * padding) / member.name
    source = captured_root / member
    source.parent.mkdir(parents=True)
    content = b"generated original managed asset"
    source.write_bytes(content)
    old_staging_member = root / "recoveries" / ".t" / destination_name / member
    assert len(str(target / member)) == published_length
    assert len(str(old_staging_member)) == published_length + 3
    assert len(str(old_staging_member) + ".part") == published_length + 8

    created = client.post("/api/v1/backups", json={}).raise_for_status().json()
    factory = cast(FastAPI, client.app).state.session_factory
    assert process_backup_job(test_settings, factory, created["job"]["id"])
    backup = created["backup"]
    shutil.copytree(captured_root, root)
    monkeypatch.setattr(test_settings, "data_dir", root)
    backup_member = root / backup["destination_path"] / "data" / member
    assert len(str(backup_member)) < 260 and backup_member.read_bytes() == content
    endpoint = f"/api/v1/backups/{backup['id']}"
    assert client.post(endpoint + "/verify").raise_for_status().json()["status"] == "valid"

    open_file = Path.open

    def windows_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        if os.name == "nt" and len(str(path)) >= 260 and not str(path).startswith("\\\\?\\"):
            raise FileNotFoundError(2, "File path exceeds the classic Windows limit", str(path))
        return open_file(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", windows_open)
    request = (
        client.post(endpoint + "/restore", json={"destination_name": destination_name})
        .raise_for_status()
        .json()
    )
    assert process_restore_job(test_settings, factory, request["job"]["id"])
    published = target / member
    readable = published if published_length < 260 else backup_io_path(published)
    assert readable.read_bytes() == backup_member.read_bytes() == source.read_bytes()
    assert (target / backup["database_filename"]).is_file()
    duplicate = client.post(endpoint + "/restore", json={"destination_name": destination_name})
    assert duplicate.status_code == 409 and "already exists" in duplicate.json()["detail"]
    assert readable.read_bytes() == content


@pytest.mark.skipif(os.name != "nt", reason="Windows path syntax")
def test_backup_filesystem_path_qualifies_drive_and_unc_roots() -> None:
    assert str(backup_io_path(Path("C:/data"))) == r"\\?\C:\data"
    assert str(backup_io_path(Path("//server/share/data"))) == r"\\?\UNC\server\share\data"
    assert backup_io_path(backup_io_path(Path("C:/data"))) == backup_io_path(Path("C:/data"))
    assert backup_io_path(Path("projects/member")) == Path("projects/member")


@pytest.mark.parametrize("after_publication", [False, True])
def test_interrupted_restore_keeps_other_staging_and_allows_safe_retry(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    after_publication: bool,
) -> None:
    _, backup = create_completed_backup(client, test_settings)
    factory = cast(FastAPI, client.app).state.session_factory
    root = test_settings.resolved_data_dir
    endpoint = f"/api/v1/backups/{backup['id']}"
    target = root / "recoveries" / "retry"
    other_stage = root / "recoveries" / ".t" / "retry"
    other_stage.mkdir(parents=True)
    sentinel = other_stage / "other-writer.txt"
    sentinel.write_bytes(b"independent stage owner")
    request = (
        client.post(endpoint + "/restore", json={"destination_name": "retry"})
        .raise_for_status()
        .json()
    )
    job_id = request["job"]["id"]
    assert client.post(endpoint + "/restore", json={"destination_name": "retry"}).status_code == 409

    def interrupt_after_copy(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("Synthetic interruption after staging the restored files")

    open_file = Path.open

    def inaccessible_published_file(path: Path, *args: Any, **kwargs: Any) -> Any:
        if path.is_relative_to(backup_io_path(target)):
            raise PermissionError("Synthetic interruption while reopening the recovery")
        return open_file(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        if after_publication:
            patch.setattr(Path, "open", inaccessible_published_file)
        else:
            patch.setattr(restores, "_verify_restored_copy", interrupt_after_copy)
        assert not process_restore_job(test_settings, factory, job_id)
    failed = client.get(f"/api/v1/jobs/{job_id}").raise_for_status().json()
    assert failed["status"] == "failed"
    expected = "could not be opened" if after_publication else "Synthetic interruption"
    assert expected in failed["error_message"]
    assert not target.exists()
    assert not any((root / ".t").iterdir())
    assert sentinel.read_bytes() == b"independent stage owner"
    assert client.post(endpoint + "/verify").raise_for_status().json()["status"] == "valid"

    retry = (
        client.post(endpoint + "/restore", json={"destination_name": "retry"})
        .raise_for_status()
        .json()
    )
    assert process_restore_job(test_settings, factory, retry["job"]["id"])
    assert (target / "restore-receipt.json").is_file()
    assert sentinel.read_bytes() == b"independent stage owner"


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
