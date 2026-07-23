"""Persistent storage-directory preferences for desktop and local deployments."""

from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from reefvision.config import (
    STORAGE_SETTING_FIELDS,
    Settings,
    load_storage_overrides,
    storage_environment_locked,
    storage_settings_path,
    write_storage_overrides,
)

router = APIRouter(tags=["system", "storage-settings"])


class StoragePathState(BaseModel):
    key: str
    label: str
    description: str
    active_path: str
    pending_path: str
    exists: bool
    writable: bool
    free_bytes: int | None
    restart_required: bool
    environment_variable: str
    environment_locked: bool


class StorageSettingsResponse(BaseModel):
    settings_file: str
    restart_required: bool
    paths: list[StoragePathState]
    notes: list[str]


class StorageSettingsUpdateRequest(BaseModel):
    data_dir: str = Field(min_length=1, max_length=4096)
    model_cache_dir: str = Field(min_length=1, max_length=4096)
    temp_dir: str = Field(min_length=1, max_length=4096)
    acknowledge_restart: bool = False


_PATH_METADATA: dict[str, tuple[str, str]] = {
    "data_dir": (
        "Application data root",
        (
            "Database, projects, imported media, managed artifacts, exports, "
            "logs, and backups."
        ),
    ),
    "model_cache_dir": (
        "Model and download cache",
        (
            "Downloadable model checkpoints, provider packs, Hugging Face, "
            "Transformers, and Torch caches."
        ),
    ),
    "temp_dir": (
        "Temporary workspace",
        (
            "Temporary files created during imports, exports, model work, and "
            "other processing."
        ),
    ),
}


def _active_paths(settings: Settings) -> dict[str, Path]:
    return {
        "data_dir": settings.resolved_data_dir,
        "model_cache_dir": settings.resolved_model_cache_dir,
        "temp_dir": settings.resolved_temp_dir,
    }


def _normalize_path(value: str, *, field_name: str) -> Path:
    path = Path(value.strip()).expanduser()
    if not path.is_absolute():
        raise HTTPException(
            status_code=400,
            detail=f"{_PATH_METADATA[field_name][0]} must be an absolute path.",
        )
    try:
        return path.resolve()
    except OSError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Could not resolve {field_name}: {exc}",
        ) from exc


def _probe_path(path: Path, *, create: bool) -> tuple[bool, bool, int | None]:
    try:
        if path.exists() and not path.is_dir():
            return True, False, None
        if create:
            path.mkdir(parents=True, exist_ok=True)
        if not path.is_dir():
            return False, False, None
        probe = path / f".reefvision-write-test-{uuid4().hex}.tmp"
        probe.write_bytes(b"reefvision-storage-probe")
        probe.unlink()
        return True, True, shutil.disk_usage(path).free
    except OSError:
        return False, False, None


def _environment_name(field_name: str) -> str:
    return f"REEFVISION_{field_name.upper()}"


def _response(settings: Settings) -> StorageSettingsResponse:
    active = _active_paths(settings)
    overrides = load_storage_overrides()
    states: list[StoragePathState] = []
    notes = [
        "Saved directory changes take effect after ReefVision restarts.",
        (
            "Changing the application data root does not copy existing projects "
            "automatically. Move or restore the existing data before switching roots."
        ),
        (
            "Exports stay inside the application data root so project records and their "
            "generated outputs remain portable together."
        ),
        (
            "Changing the model cache may require downloadable model checkpoints and "
            "provider packs to be installed again."
        ),
    ]
    for field_name in STORAGE_SETTING_FIELDS:
        environment_name = _environment_name(field_name)
        environment_locked = storage_environment_locked(field_name)
        active_path = active[field_name]
        configured = overrides.get(field_name)
        pending_path = (
            active_path
            if environment_locked or not configured
            else Path(configured).expanduser().resolve()
        )
        exists, writable, free_bytes = _probe_path(pending_path, create=False)
        label, description = _PATH_METADATA[field_name]
        states.append(
            StoragePathState(
                key=field_name,
                label=label,
                description=description,
                active_path=str(active_path),
                pending_path=str(pending_path),
                exists=exists,
                writable=writable,
                free_bytes=free_bytes,
                restart_required=pending_path != active_path,
                environment_variable=environment_name,
                environment_locked=environment_locked,
            )
        )
        if environment_locked:
            notes.append(
                f"{label} is controlled by {environment_name}; "
                "the in-app field is read-only."
            )
    return StorageSettingsResponse(
        settings_file=str(storage_settings_path()),
        restart_required=any(item.restart_required for item in states),
        paths=states,
        notes=notes,
    )


@router.get("/system/storage-settings", response_model=StorageSettingsResponse)
def get_storage_settings(request: Request) -> StorageSettingsResponse:
    settings: Settings = request.app.state.settings
    return _response(settings)


@router.put("/system/storage-settings", response_model=StorageSettingsResponse)
def update_storage_settings(
    payload: StorageSettingsUpdateRequest,
    request: Request,
) -> StorageSettingsResponse:
    settings: Settings = request.app.state.settings
    requested_values = {
        "data_dir": payload.data_dir,
        "model_cache_dir": payload.model_cache_dir,
        "temp_dir": payload.temp_dir,
    }
    active = _active_paths(settings)
    normalized: dict[str, Path] = {}

    for field_name, value in requested_values.items():
        environment_name = _environment_name(field_name)
        candidate = _normalize_path(value, field_name=field_name)
        if storage_environment_locked(field_name) and candidate != active[field_name]:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{_PATH_METADATA[field_name][0]} is controlled by "
                    f"{environment_name}. Remove that environment override "
                    "before changing it here."
                ),
            )
        normalized[field_name] = candidate

    changed = any(
        normalized[field_name] != active[field_name]
        for field_name in STORAGE_SETTING_FIELDS
    )
    if changed and not payload.acknowledge_restart:
        raise HTTPException(
            status_code=400,
            detail=(
                "Confirm that ReefVision must restart before directory changes "
                "take effect. Existing project data is not moved automatically."
            ),
        )

    for candidate in normalized.values():
        exists, writable, _ = _probe_path(candidate, create=True)
        if not exists or not writable:
            raise HTTPException(
                status_code=400,
                detail=f"ReefVision cannot create or write to {candidate}.",
            )

    write_storage_overrides(
        {field_name: str(path) for field_name, path in normalized.items()}
    )
    return _response(settings)
