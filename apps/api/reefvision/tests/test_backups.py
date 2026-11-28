from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.jobs.backups import process_backup_job
from reefvision.jobs.restores import process_restore_job
from reefvision.jobs.worker import process_thumbnail_job
from reefvision.storage.backups import write_backup_completion_marker, write_backup_manifest
from reefvision.storage.worker_lock import worker_leadership

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


def test_backup_succeeds_while_profile_workers_hold_their_locks(
    client: TestClient, test_settings: Settings
) -> None:
    root = test_settings.resolved_data_dir
    nested = root / "projects" / "example" / "compute-worker.lock"
    nested.parent.mkdir(parents=True)
    nested.write_bytes(b"portable project attachment")
    with (
        worker_leadership(root) as worker,
        worker_leadership(root / "runtime", filename="headless-session.lock") as session,
    ):
        assert worker and session
        _, backup = create_completed_backup(client, test_settings)
    manifest = json.loads((root / backup["manifest_path"]).read_bytes())
    names = {entry["path"] for entry in manifest["file_inventory"]}
    assert "data/compute-worker.lock" not in names
    assert "data/runtime/headless-session.lock" not in names
    assert "data/projects/example/compute-worker.lock" in names


def test_restore_verifies_old_worker_locks_and_omits_them_from_the_recovery(
    client: TestClient, test_settings: Settings
) -> None:
    root = test_settings.resolved_data_dir
    _, backup = create_completed_backup(client, test_settings)
    media = root / backup["destination_path"]
    manifest_path = root / backup["manifest_path"]
    marker_path = root / backup["completion_marker_path"]
    manifest = json.loads(manifest_path.read_bytes())
    marker = json.loads(marker_path.read_bytes())
    payload = b"old worker state"
    for relative in ("data/compute-worker.lock", "data/runtime/headless-session.lock"):
        member = media / relative
        member.parent.mkdir(parents=True, exist_ok=True)
        member.write_bytes(payload)
        manifest["file_inventory"].append(
            {"path": relative, "size_bytes": len(payload), "sha256": sha256(payload).hexdigest()}
        )
        manifest["total_expected_size_bytes"] += len(payload)
    marker["manifest_sha256"], _ = write_backup_manifest(manifest_path, manifest)
    write_backup_completion_marker(marker_path, marker)
    route = f"/api/v1/backups/{backup['id']}"
    assert client.post(route + "/verify").json()["status"] == "valid"
    response = client.post(route + "/restore", json={"destination_name": "old-worker-copy"})
    assert response.status_code == 200, response.text
    factory = cast(FastAPI, client.app).state.session_factory
    job_id = response.json()["job"]["id"]
    assert process_restore_job(test_settings, factory, job_id)
    recovered = root / response.json()["destination_path"]
    assert (recovered / manifest["database_filename"]).is_file()
    assert not (recovered / "compute-worker.lock").exists()
    assert not (recovered / "runtime" / "headless-session.lock").exists()
    result = client.get(f"/api/v1/jobs/{job_id}").json()["result_json"]
    assert result["restored_file_count"] == len(manifest["file_inventory"]) - 2
    assert result["restored_total_size_bytes"] == manifest["total_expected_size_bytes"] - 2 * len(
        payload
    )


def test_backup_preserves_deep_live_training_asset_in_portable_inventory(
    client: TestClient, test_settings: Settings
) -> None:
    project = create_project(client, "Deep training archive")
    root = test_settings.resolved_data_dir
    relative = Path("projects") / project["id"] / "training" / project["id"] / "dataset"
    while len(str(root / relative / "images" / "train" / "frame.png")) <= 265:
        relative /= "frozen-recording-2026"
    relative = relative / "images" / "train" / "frame.png"
    fixture_root = root
    if os.name == "nt":
        # Seed the full NTFS name independently of the application's storage code.
        name = root.as_posix()
        fixture_root = Path("//?/UNC/" + name[2:] if name.startswith("//") else "//?/" + name)
    member = fixture_root / relative
    member.parent.mkdir(parents=True)
    content = b"original offline training member"
    member.write_bytes(content)
    _, backup = create_completed_backup(client, test_settings)
    manifest = json.loads((root / backup["manifest_path"]).read_bytes())
    asset_name = "data/" + relative.as_posix()
    rows = [entry for entry in manifest["file_inventory"] if entry["path"] == asset_name]
    assert len(rows) == 1
    assert rows[0]["sha256"] == sha256(content).hexdigest()
    assert rows[0]["size_bytes"] == len(content)
    assert "data/test.db" not in {entry["path"] for entry in manifest["file_inventory"]}
    verification = client.post(f"/api/v1/backups/{backup['id']}/verify")
    assert verification.status_code == 200
    assert verification.json()["status"] == "valid"
    assert member.read_bytes() == content


def test_backup_after_restore_keeps_live_assets_without_recapturing_recoveries(
    client: TestClient, test_settings: Settings
) -> None:
    root = test_settings.resolved_data_dir
    project = create_project(client, "Archive scope")
    nested = root / "projects" / project["id"] / "recoveries" / "observations.csv"
    nested.parent.mkdir(parents=True)
    nested.write_bytes(b"specimen,date\nA,2026-11-20\n")
    _, original = create_completed_backup(client, test_settings)
    factory = cast(FastAPI, client.app).state.session_factory
    original_manifest = (root / original["manifest_path"]).read_bytes()
    first_assets = {
        row["path"]: row["sha256"]
        for row in json.loads(original_manifest)["file_inventory"]
        if row["path"].startswith("data/")
    }
    assert f"data/{nested.relative_to(root).as_posix()}" in first_assets

    restore = client.post(
        f"/api/v1/backups/{original['id']}/restore", json={"destination_name": "first-copy"}
    )
    assert restore.status_code == 200, restore.text
    assert process_restore_job(test_settings, factory, restore.json()["job"]["id"])
    recovered = root / restore.json()["destination_path"] / nested.relative_to(root)
    assert recovered.read_bytes() == nested.read_bytes()
    staging = root / ".t" / "other-active-job" / "unfinished.png"
    staging.parent.mkdir(parents=True)
    staging.write_bytes(b"active restoration")

    reply = client.post("/api/v1/backups", json={"include_exports": False, "include_logs": False})
    assert reply.status_code == 201, reply.text
    assert process_backup_job(test_settings, factory, reply.json()["job"]["id"])
    later = reply.json()["backup"]
    manifest = json.loads((root / later["manifest_path"]).read_bytes())
    assert {
        row["path"]: row["sha256"]
        for row in manifest["file_inventory"]
        if row["path"].startswith("data/")
    } == first_assets
    assert "recoveries" in manifest["excluded_sections"]
    for backup in (original, later):
        verification = client.post(f"/api/v1/backups/{backup['id']}/verify")
        assert verification.status_code == 200
        assert verification.json()["status"] == "valid"
    assert (root / original["manifest_path"]).read_bytes() == original_manifest
    assert recovered.read_bytes() == nested.read_bytes()
    assert staging.read_bytes() == b"active restoration"


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


def test_subsequent_backup_excludes_managed_backup_directories(
    client: TestClient, test_settings: Settings
) -> None:
    _, first = create_completed_backup(client, test_settings)
    assert first["status"] == "completed"
    response = client.post("/api/v1/backups", json={})
    assert response.status_code == 201, response.text
    created = response.json()
    app = cast(FastAPI, client.app)
    assert process_backup_job(test_settings, app.state.session_factory, created["job"]["id"])
    second = client.get(f"/api/v1/backups/{created['backup']['id']}").json()
    assert second["status"] == "completed"
    manifest_path = test_settings.resolved_data_dir / Path(second["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert all(not item["path"].startswith("data/bk/") for item in manifest["file_inventory"])
    verification = client.post(f"/api/v1/backups/{second['id']}/verify")
    assert verification.status_code == 200, verification.text
    assert verification.json()["status"] == "valid"


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
