from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from reefvision.config import (
    Settings,
    clear_settings_cache,
    get_settings,
    storage_settings_path,
    write_storage_overrides,
)


def _paths(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    items = payload["paths"]
    assert isinstance(items, list)
    return {str(item["key"]): item for item in items if isinstance(item, dict)}


def test_storage_settings_report_active_paths(
    client: TestClient,
    test_settings: Settings,
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))
    for name in ("REEFVISION_DATA_DIR", "REEFVISION_MODEL_CACHE_DIR", "REEFVISION_TEMP_DIR"):
        monkeypatch.delenv(name, raising=False)

    response = client.get("/api/v1/system/storage-settings")

    assert response.status_code == 200
    payload = response.json()
    paths = _paths(payload)
    assert paths["data_dir"]["active_path"] == str(test_settings.resolved_data_dir)
    assert paths["model_cache_dir"]["active_path"] == str(
        test_settings.resolved_model_cache_dir
    )
    assert paths["temp_dir"]["active_path"] == str(test_settings.resolved_temp_dir)
    assert payload["restart_required"] is False
    assert payload["settings_file"] == str(storage_settings_path())


def test_storage_settings_require_restart_acknowledgement(
    client: TestClient,
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))
    for name in ("REEFVISION_DATA_DIR", "REEFVISION_MODEL_CACHE_DIR", "REEFVISION_TEMP_DIR"):
        monkeypatch.delenv(name, raising=False)
    payload = {
        "data_dir": str((tmp_path / "external" / "data").resolve()),
        "model_cache_dir": str((tmp_path / "external" / "models").resolve()),
        "temp_dir": str((tmp_path / "external" / "temp").resolve()),
        "acknowledge_restart": False,
    }

    response = client.put("/api/v1/system/storage-settings", json=payload)

    assert response.status_code == 400
    assert "must restart" in response.json()["detail"]


def test_storage_settings_persist_writable_external_paths(
    client: TestClient,
    test_settings: Settings,
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))
    for name in ("REEFVISION_DATA_DIR", "REEFVISION_MODEL_CACHE_DIR", "REEFVISION_TEMP_DIR"):
        monkeypatch.delenv(name, raising=False)
    requested = {
        "data_dir": str((tmp_path / "external" / "data").resolve()),
        "model_cache_dir": str((tmp_path / "external" / "models").resolve()),
        "temp_dir": str((tmp_path / "external" / "temp").resolve()),
        "acknowledge_restart": True,
    }

    response = client.put("/api/v1/system/storage-settings", json=requested)

    assert response.status_code == 200
    payload = response.json()
    paths = _paths(payload)
    assert payload["restart_required"] is True
    for key in ("data_dir", "model_cache_dir", "temp_dir"):
        assert paths[key]["active_path"] != paths[key]["pending_path"]
        assert paths[key]["pending_path"] == requested[key]
        assert paths[key]["exists"] is True
        assert paths[key]["writable"] is True
    assert paths["data_dir"]["active_path"] == str(test_settings.resolved_data_dir)

    settings_file = Path(payload["settings_file"])
    saved = json.loads(settings_file.read_text(encoding="utf-8"))
    assert saved["paths"]["data_dir"] == requested["data_dir"]


def test_storage_settings_respect_environment_lock(
    client: TestClient,
    test_settings: Settings,
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))
    monkeypatch.setenv("REEFVISION_DATA_DIR", str(test_settings.resolved_data_dir))

    response = client.put(
        "/api/v1/system/storage-settings",
        json={
            "data_dir": str((tmp_path / "other-data").resolve()),
            "model_cache_dir": str(test_settings.resolved_model_cache_dir),
            "temp_dir": str(test_settings.resolved_temp_dir),
            "acknowledge_restart": True,
        },
    )

    assert response.status_code == 400
    assert "REEFVISION_DATA_DIR" in response.json()["detail"]


def test_get_settings_loads_persisted_storage_roots(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))
    for name in ("REEFVISION_DATA_DIR", "REEFVISION_MODEL_CACHE_DIR", "REEFVISION_TEMP_DIR"):
        monkeypatch.delenv(name, raising=False)
    requested = {
        "data_dir": str((tmp_path / "persisted" / "data").resolve()),
        "model_cache_dir": str((tmp_path / "persisted" / "models").resolve()),
        "temp_dir": str((tmp_path / "persisted" / "temp").resolve()),
    }
    write_storage_overrides(requested)
    clear_settings_cache()
    try:
        settings = get_settings()
        assert settings.resolved_data_dir == Path(requested["data_dir"])
        assert settings.resolved_model_cache_dir == Path(requested["model_cache_dir"])
        assert settings.resolved_temp_dir == Path(requested["temp_dir"])
    finally:
        clear_settings_cache()
