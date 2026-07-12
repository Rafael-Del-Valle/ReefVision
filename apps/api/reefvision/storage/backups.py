"""Managed backup storage helpers for Milestone 8."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sqlite3
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy.engine import make_url

from reefvision import __version__
from reefvision.config import Settings
from reefvision.domain.errors import ValidationError
from reefvision.storage.datasets import canonical_json_bytes, canonical_json_sha256
from reefvision.storage.projects import resolve_managed_project_path

BACKUP_FORMAT_VERSION = "1.0"
BACKUP_MANIFEST_FILENAME = "backup-manifest.json"
BACKUP_COMPLETION_MARKER_FILENAME = "backup-complete.json"


@dataclass(frozen=True)
class BackupFileCandidate:
    source_path: Path
    backup_path: str
    size_bytes: int


@dataclass(frozen=True)
class BackupPlan:
    source_data_dir: Path
    database_source_path: Path
    database_filename: str
    database_backup_path: str
    data_files: list[BackupFileCandidate]
    included_sections: list[str]
    excluded_sections: list[str]
    estimated_total_size_bytes: int

    @property
    def estimated_file_count(self) -> int:
        return len(self.data_files) + 1


def resolve_database_path(settings: Settings) -> Path:
    url = make_url(settings.resolved_database_url)
    if url.get_backend_name() != "sqlite":
        raise ValidationError("Milestone 8 backups currently support SQLite ReefVision databases")
    database = url.database
    if database in (None, "", ":memory:"):
        raise ValidationError("Milestone 8 backups require a file-backed SQLite database")
    assert database is not None
    return Path(database).resolve()


def default_backup_paths(
    backup_id: str,
    *,
    created_at_label: str,
    database_filename: str,
) -> tuple[str, str, str, str]:
    _ = created_at_label
    root = f"bk/{backup_id[:8]}"
    staging = f"bk/.t/{backup_id[:8]}"
    manifest = f"{root}/{BACKUP_MANIFEST_FILENAME}"
    completion = f"{root}/{BACKUP_COMPLETION_MARKER_FILENAME}"
    _ = database_filename
    return root, staging, manifest, completion


def backup_root_path(settings: Settings, relative_path: str) -> Path:
    return resolve_managed_project_path(settings, relative_path)


def build_backup_plan(
    settings: Settings,
    *,
    database_path: Path,
    include_exports: bool,
    include_logs: bool,
) -> BackupPlan:
    if not database_path.is_file():
        raise ValidationError("The configured ReefVision database file is missing")

    data_root = settings.resolved_data_dir
    data_files: list[BackupFileCandidate] = []
    included_sections = ["database", "projects", "thumbnails", "models"]
    excluded_sections = ["backups", "transient staging directories"]
    if include_logs:
        included_sections.append("logs")
    else:
        excluded_sections.append("logs")
    if include_exports:
        included_sections.append("exports")
    else:
        excluded_sections.append("exports")

    for path in sorted(data_root.rglob("*")):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if resolved == database_path:
            continue
        relative = path.relative_to(data_root)
        if _should_exclude(relative, include_exports=include_exports, include_logs=include_logs):
            continue
        data_files.append(
            BackupFileCandidate(
                source_path=path,
                backup_path=f"data/{relative.as_posix()}",
                size_bytes=path.stat().st_size,
            )
        )

    return BackupPlan(
        source_data_dir=data_root,
        database_source_path=database_path,
        database_filename=database_path.name,
        database_backup_path=f"database/{database_path.name}",
        data_files=sorted(data_files, key=lambda item: item.backup_path),
        included_sections=sorted(set(included_sections)),
        excluded_sections=sorted(set(excluded_sections)),
        estimated_total_size_bytes=database_path.stat().st_size
        + sum(item.size_bytes for item in data_files),
    )


def create_sqlite_snapshot(source_path: Path, destination_path: Path) -> None:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination_path.with_suffix(destination_path.suffix + ".part")
    temporary.unlink(missing_ok=True)
    source = sqlite3.connect(source_path)
    destination = sqlite3.connect(temporary)
    try:
        try:
            source.backup(destination)
            destination.commit()
        finally:
            destination.close()
            source.close()
        _fsync_file(temporary)
        os.replace(temporary, destination_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def copy_file_with_sha256(source_path: Path, destination_path: Path) -> tuple[str, int]:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination_path.with_suffix(destination_path.suffix + ".part")
    temporary.unlink(missing_ok=True)
    digest = hashlib.sha256()
    total = 0
    try:
        with source_path.open("rb") as source, temporary.open("xb") as destination:
            while chunk := source.read(1024 * 1024):
                destination.write(chunk)
                digest.update(chunk)
                total += len(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary, destination_path)
        return digest.hexdigest(), total
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            total += len(chunk)
    return digest.hexdigest(), total


def write_backup_manifest(path: Path, manifest: dict[str, Any]) -> tuple[str, int]:
    payload = canonical_json_bytes(manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    _fsync_file(path)
    return canonical_json_sha256(manifest), len(payload)


def write_backup_completion_marker(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(payload))
    _fsync_file(path)


def build_manifest(
    *,
    backup_id: str,
    created_at: str,
    current_schema_revision: str | None,
    plan: BackupPlan,
    file_inventory: list[dict[str, Any]],
    item_counts: dict[str, int],
    notes: str | None,
) -> dict[str, Any]:
    return {
        "backup_id": backup_id,
        "backup_format_version": BACKUP_FORMAT_VERSION,
        "reefvision_application_version": __version__,
        "database_schema_revision": current_schema_revision,
        "created_at": created_at,
        "source_platform": platform.platform(),
        "source_application_data": {
            "display_name": plan.source_data_dir.name,
            "path_fingerprint_sha256": hashlib.sha256(
                str(plan.source_data_dir).encode("utf-8")
            ).hexdigest(),
        },
        "database_filename": plan.database_filename,
        "included_sections": list(plan.included_sections),
        "excluded_sections": list(plan.excluded_sections),
        "item_counts": {key: int(value) for key, value in sorted(item_counts.items())},
        "file_inventory": sorted(file_inventory, key=lambda item: str(item["path"])),
        "total_expected_size_bytes": int(sum(int(item["size_bytes"]) for item in file_inventory)),
        "compatibility": {
            "backup_format_version": BACKUP_FORMAT_VERSION,
            "reefvision_application_version": __version__,
            "database_schema_revision": current_schema_revision,
        },
        "user_notes": notes,
    }


def verify_backup_directory(backup_root: Path, *, backup_id: str) -> dict[str, Any]:
    manifest_path = backup_root / BACKUP_MANIFEST_FILENAME
    completion_path = backup_root / BACKUP_COMPLETION_MARKER_FILENAME
    errors: list[str] = []
    warnings: list[str] = []
    missing_files: list[str] = []
    checksum_failures: list[str] = []
    duplicate_entries: list[str] = []
    item_counts: dict[str, int] = {}
    format_version: str | None = None
    application_version: str | None = None
    current_schema_revision: str | None = None
    database_filename: str | None = None
    total_size_bytes: int | None = None
    file_count = 0

    manifest: dict[str, Any] | None = None
    if not manifest_path.is_file():
        errors.append("Backup manifest is missing.")
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"Backup manifest could not be read: {exc}")

    if manifest is not None:
        format_version = _string_value(manifest.get("backup_format_version"))
        application_version = _string_value(manifest.get("reefvision_application_version"))
        current_schema_revision = _string_value(manifest.get("database_schema_revision"))
        database_filename = _string_value(manifest.get("database_filename"))
        raw_item_counts = manifest.get("item_counts")
        if isinstance(raw_item_counts, dict):
            item_counts = {
                str(key): int(value)
                for key, value in raw_item_counts.items()
                if isinstance(value, int | float)
            }
        raw_total_size = manifest.get("total_expected_size_bytes")
        if isinstance(raw_total_size, int):
            total_size_bytes = raw_total_size
        if format_version != BACKUP_FORMAT_VERSION:
            warnings.append(
                "This ReefVision build only supports backup format "
                f"{BACKUP_FORMAT_VERSION}; found {format_version or 'unknown'}."
            )

        inventory = manifest.get("file_inventory")
        if not isinstance(inventory, list):
            errors.append("Backup manifest file inventory is missing or invalid.")
            inventory = []
        else:
            seen_paths: set[str] = set()
            computed_total = 0
            file_count = len(inventory)
            for entry in inventory:
                if not isinstance(entry, dict):
                    errors.append("Backup manifest contains a non-object inventory entry.")
                    continue
                relative_path = _string_value(entry.get("path"))
                expected_sha256 = _string_value(entry.get("sha256"))
                size_bytes = entry.get("size_bytes")
                if (
                    relative_path is None
                    or expected_sha256 is None
                    or not isinstance(size_bytes, int)
                    or size_bytes < 0
                ):
                    errors.append("Backup manifest contains an invalid inventory entry.")
                    continue
                if relative_path in seen_paths:
                    duplicate_entries.append(relative_path)
                    continue
                seen_paths.add(relative_path)
                computed_total += size_bytes
                path = backup_root / PurePosixPath(relative_path)
                if not path.is_file():
                    missing_files.append(relative_path)
                    continue
                actual_sha256, actual_size = hash_file(path)
                if actual_size != size_bytes:
                    checksum_failures.append(relative_path)
                    continue
                if actual_sha256 != expected_sha256:
                    checksum_failures.append(relative_path)
            if total_size_bytes is not None and computed_total != total_size_bytes:
                warnings.append("The manifest total size does not match the inventory sum.")

    completion_marker_present = completion_path.is_file()
    if completion_marker_present:
        try:
            completion = json.loads(completion_path.read_text(encoding="utf-8"))
            if not isinstance(completion, dict):
                raise ValueError("Completion marker is not a JSON object")
            expected_backup_id = _string_value(completion.get("backup_id"))
            if expected_backup_id != backup_id:
                errors.append("Completion marker does not match the requested backup ID.")
            if manifest is not None:
                expected_manifest_sha = _string_value(completion.get("manifest_sha256"))
                actual_manifest_sha = canonical_json_sha256(manifest)
                if expected_manifest_sha != actual_manifest_sha:
                    errors.append(
                        "Completion marker manifest checksum does not match the manifest."
                    )
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"Completion marker could not be read: {exc}")
    else:
        errors.append("Backup completion marker is missing.")

    if format_version not in (None, BACKUP_FORMAT_VERSION):
        status = "unsupported"
    elif errors or missing_files or checksum_failures or duplicate_entries:
        status = "invalid"
    elif warnings:
        status = "valid_with_warnings"
    else:
        status = "valid"

    return {
        "backup_id": backup_id,
        "status": status,
        "format_version": format_version,
        "application_version": application_version,
        "current_schema_revision": current_schema_revision,
        "completion_marker_present": completion_marker_present,
        "manifest_path": str(manifest_path),
        "database_filename": database_filename,
        "file_count": file_count,
        "total_size_bytes": total_size_bytes,
        "item_counts": item_counts,
        "missing_files": sorted(missing_files),
        "checksum_failures": sorted(checksum_failures),
        "duplicate_entries": sorted(duplicate_entries),
        "warnings": warnings,
        "errors": errors,
    }


def _should_exclude(
    relative_path: Path,
    *,
    include_exports: bool,
    include_logs: bool,
) -> bool:
    parts = relative_path.parts
    if not parts:
        return False
    if parts[0] == "backups":
        return True
    if parts[0] == "logs" and not include_logs:
        return True
    if ".imports" in parts or ".model-imports" in parts:
        return True
    if relative_path.name.endswith(".part"):
        return True
    return bool(
        not include_exports and len(parts) >= 3 and parts[0] == "projects" and parts[2] == "exports"
    )


def _fsync_file(path: Path) -> None:
    with path.open("r+b") as handle:
        os.fsync(handle.fileno())


def _string_value(value: object) -> str | None:
    return value if isinstance(value, str) else None
