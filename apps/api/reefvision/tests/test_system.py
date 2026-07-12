from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient

from reefvision import __version__
from reefvision.config import Settings
from reefvision.services.system import SystemService
from reefvision.storage.backups import BACKUP_FORMAT_VERSION


def set_alembic_revision(database_path: Path, revision: str) -> None:
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32))")
        connection.execute("DELETE FROM alembic_version")
        connection.execute("INSERT INTO alembic_version(version_num) VALUES (?)", (revision,))
        connection.commit()
    finally:
        connection.close()


def current_head_revision() -> str:
    api_root = Path(__file__).resolve().parents[2]
    config = Config(str(api_root / "alembic.ini"))
    config.attributes["configure_logger"] = False
    config.set_main_option("script_location", str(api_root / "migrations"))
    script = ScriptDirectory.from_config(config)
    head = script.get_current_head()
    assert head is not None
    return head


def test_system_version_reports_paths_and_schema(
    client: TestClient, test_settings: Settings
) -> None:
    response = client.get("/api/v1/system/version")

    assert response.status_code == 200
    payload = response.json()
    assert payload["application_version"] == __version__
    assert payload["backup_format_version"] == BACKUP_FORMAT_VERSION
    assert payload["environment"] == "test"
    assert payload["data_dir"] == str(test_settings.resolved_data_dir)
    assert payload["safe_mode"] is False
    assert payload["database_path"].endswith("test.db")
    assert payload["expected_schema_revision"] == current_head_revision()
    assert payload["current_schema_revision"] is None


def test_system_service_uses_resolved_alembic_paths(
    client: TestClient,
    monkeypatch,
) -> None:
    api_root = Path(__file__).resolve().parents[2]
    expected_ini = api_root / "alembic.ini"
    expected_migrations = api_root / "migrations"

    monkeypatch.setattr(
        "reefvision.services.system.resolve_alembic_paths",
        lambda: (expected_ini, expected_migrations),
    )

    service = SystemService(client.app.state.settings, client.app.state.engine)
    script = service._alembic_script_directory()

    assert Path(script.dir) == expected_migrations
    assert script.get_current_head() == current_head_revision()


def test_system_compatibility_reports_pending_migrations_for_blank_db(client: TestClient) -> None:
    response = client.get("/api/v1/system/compatibility")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_status"] == "uninitialized"
    assert payload["compatible_for_read_write"] is True
    assert payload["pending_revisions"][-1] == current_head_revision()


def test_system_compatibility_detects_database_behind_code(
    client: TestClient, test_settings: Settings
) -> None:
    set_alembic_revision(test_settings.resolved_data_dir.parent / "test.db", "0007")

    response = client.get("/api/v1/system/compatibility")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_status"] == "migration_required"
    assert payload["current_schema_revision"] == "0007"
    assert payload["expected_schema_revision"] == current_head_revision()
    assert payload["pending_revisions"][0] == "0008"
    assert payload["pending_revisions"][-1] == current_head_revision()


def test_system_preflight_blocks_unknown_newer_database_revision(
    client: TestClient, test_settings: Settings
) -> None:
    set_alembic_revision(test_settings.resolved_data_dir.parent / "test.db", "9999")

    response = client.post("/api/v1/system/migrations/preflight")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_status"] == "database_newer_than_code"
    assert payload["compatible_for_upgrade"] is False
    assert payload["blocking_issues"]


def test_system_logs_location_reports_api_log_file(
    client: TestClient, test_settings: Settings
) -> None:
    response = client.get("/api/v1/system/logs/location")

    assert response.status_code == 200
    payload = response.json()
    assert payload["logs_dir"] == str(test_settings.resolved_data_dir / "logs")
    assert any(item["name"] == "api.log" for item in payload["files"])


def test_system_command_shortcuts_report_repair_required(
    client: TestClient, monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("Path", r"C:\Windows\System32")

    response = client.get("/api/v1/system/command-shortcuts")

    assert response.status_code == 200
    payload = response.json()
    assert payload["command_version"] == __version__
    assert payload["path_contains_command_directory"] is False
    assert payload["start_command_exists"] is False
    assert payload["update_command_exists"] is False
    assert payload["verification_result"] == "repair_required"
    assert payload["notes"]


def test_system_command_shortcut_repair_runs_installer(
    client: TestClient, monkeypatch, tmp_path: Path
) -> None:
    command_root = tmp_path / "ReefVision"
    command_dir = command_root / "bin"
    support_dir = command_root / "commands"
    config_dir = command_root / "config"
    repo_path = Path(__file__).resolve().parents[4]

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("Path", f"{command_dir};C:\\Windows\\System32")

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert str(repo_path / "scripts" / "install-reefvision-commands.ps1") in command
        command_dir.mkdir(parents=True, exist_ok=True)
        support_dir.mkdir(parents=True, exist_ok=True)
        config_dir.mkdir(parents=True, exist_ok=True)
        (command_dir / "start-reefvision.cmd").write_text(
            ":: ReefVision managed command wrapper\n@echo off\n",
            encoding="utf-8",
        )
        (command_dir / "update-reefvision.cmd").write_text(
            ":: ReefVision managed command wrapper\n@echo off\n",
            encoding="utf-8",
        )
        (support_dir / "start-reefvision.ps1").write_text(
            "# ReefVision start helper\n",
            encoding="utf-8",
        )
        (support_dir / "update-reefvision.ps1").write_text(
            "# ReefVision update helper\n",
            encoding="utf-8",
        )
        (config_dir / "commands.json").write_text(
            json.dumps({"repo_path": str(repo_path)}),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="shortcut repair ok", stderr="")

    monkeypatch.setattr("reefvision.services.system.subprocess.run", fake_run)

    response = client.post("/api/v1/system/command-shortcuts/repair")

    assert response.status_code == 200
    payload = response.json()
    assert payload["output"] == "shortcut repair ok"
    assert payload["status"]["verification_result"] == "ready"
    assert payload["status"]["path_contains_command_directory"] is True
    assert payload["status"]["start_command_managed"] is True
    assert payload["status"]["update_command_managed"] is True
