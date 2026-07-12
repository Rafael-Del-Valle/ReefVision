"""Managed, application-data storage for catalog checkpoints and provider packs."""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from reefvision.config import Settings
from reefvision.domain.errors import ValidationError

MANIFEST_VERSION = 1
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")
_MANIFEST_LOCK = threading.Lock()


def catalog_model_directories(settings: Settings) -> dict[str, Path]:
    root = settings.resolved_data_dir / "models"
    directories = {
        "root": root,
        "catalog_models": root / "catalog-models",
        "provider_packs": root / "provider-packs",
        "trained_models": root / "trained-models",
        "imported_models": root / "imported-models",
        "temporary_downloads": root / "temporary-downloads",
    }
    for directory in directories.values():
        directory.mkdir(parents=True, exist_ok=True)
    return directories


def _safe_catalog_segments(catalog_id: str) -> list[str]:
    segments = catalog_id.split("/")
    if not segments or any(not _SAFE_SEGMENT.fullmatch(segment) for segment in segments):
        raise ValidationError("Catalog id cannot be mapped to managed storage")
    return segments


def catalog_asset_path(settings: Settings, catalog_id: str, filename: str) -> Path:
    if Path(filename).name != filename or not _SAFE_SEGMENT.fullmatch(filename):
        raise ValidationError("Catalog filename cannot be mapped to managed storage")
    root = catalog_model_directories(settings)["catalog_models"]
    destination = root.joinpath(*_safe_catalog_segments(catalog_id), filename)
    resolved = destination.resolve()
    if root.resolve() not in resolved.parents:
        raise ValidationError("Catalog asset path escapes managed storage")
    return resolved


def relative_catalog_asset_path(settings: Settings, path: Path) -> str:
    try:
        return path.resolve().relative_to(settings.resolved_data_dir).as_posix()
    except ValueError as exc:
        raise ValidationError("Catalog asset is outside ReefVision application data") from exc


def manifest_path(settings: Settings) -> Path:
    return catalog_model_directories(settings)["catalog_models"] / "manifest.json"


def load_catalog_manifest(settings: Settings) -> dict[str, Any]:
    path = manifest_path(settings)
    if not path.is_file():
        return {"manifest_version": MANIFEST_VERSION, "assets": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"manifest_version": MANIFEST_VERSION, "assets": {}, "corrupted": True}
    assets = payload.get("assets")
    if payload.get("manifest_version") != MANIFEST_VERSION or not isinstance(assets, dict):
        return {"manifest_version": MANIFEST_VERSION, "assets": {}, "corrupted": True}
    return cast(dict[str, Any], payload)


def catalog_manifest_record(settings: Settings, catalog_id: str) -> dict[str, Any] | None:
    value = load_catalog_manifest(settings).get("assets", {}).get(catalog_id)
    return dict(value) if isinstance(value, dict) else None


def write_catalog_manifest_record(
    settings: Settings,
    catalog_id: str,
    record: dict[str, Any],
) -> None:
    path = manifest_path(settings)
    with _MANIFEST_LOCK:
        payload = load_catalog_manifest(settings)
        assets = dict(payload.get("assets", {}))
        assets[catalog_id] = {
            **record,
            "catalog_id": catalog_id,
            "installed_at": record.get("installed_at") or datetime.now(UTC).isoformat(),
        }
        finalized = {
            "manifest_version": MANIFEST_VERSION,
            "updated_at": datetime.now(UTC).isoformat(),
            "assets": assets,
        }
        temporary = path.with_suffix(".json.part")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(finalized, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)


def remove_catalog_manifest_record(settings: Settings, catalog_id: str) -> None:
    path = manifest_path(settings)
    with _MANIFEST_LOCK:
        payload = load_catalog_manifest(settings)
        assets = dict(payload.get("assets", {}))
        assets.pop(catalog_id, None)
        finalized = {
            "manifest_version": MANIFEST_VERSION,
            "updated_at": datetime.now(UTC).isoformat(),
            "assets": assets,
        }
        temporary = path.with_suffix(".json.part")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(finalized, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
