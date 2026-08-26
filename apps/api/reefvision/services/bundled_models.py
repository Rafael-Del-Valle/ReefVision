"""Seed installer-bundled catalog checkpoints into ReefVision application data."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job
from reefvision.services.model_catalog import _load_static_model_catalog
from reefvision.storage.catalog_models import (
    catalog_asset_path,
    catalog_manifest_record,
    relative_catalog_asset_path,
    write_catalog_manifest_record,
)

CHUNK_SIZE = 1024 * 1024
BUNDLE_MANIFEST_VERSION = 1


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _bundle_roots() -> list[Path]:
    candidates: list[Path] = []
    configured = os.environ.get("REEFVISION_BUNDLED_MODELS_DIR")
    if configured and not configured.isspace():
        candidates.append(Path(configured).expanduser())

    bundle_root = vars(sys).get("_MEIPASS")
    if bundle_root:
        candidates.append(Path(str(bundle_root)).resolve() / "bundled-models")

    executable = getattr(sys, "executable", None)
    if executable:
        executable_root = Path(executable).resolve().parent
        candidates.extend(
            [
                executable_root / "bundled-models",
                executable_root / "_internal" / "bundled-models",
                executable_root.parent / "bundled-models",
                executable_root.parent.parent / "bundled-models",
            ]
        )

    candidates.append(Path(__file__).resolve().parents[4] / ".desktop" / "bundled-models")

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = str(candidate.resolve(strict=False)).casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(candidate)
    return unique


def _load_bundle_manifest() -> tuple[Path, dict[str, Any]] | None:
    for root in _bundle_roots():
        manifest_path = root / "manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("manifest_version") == BUNDLE_MANIFEST_VERSION and isinstance(
            payload.get("assets"), dict
        ):
            return root, cast(dict[str, Any], payload)
    return None


def install_bundled_catalog_models(settings: Settings) -> tuple[list[str], list[str]]:
    """Copy verified installer checkpoints into the existing managed-model store."""

    loaded = _load_bundle_manifest()
    if loaded is None:
        return [], []

    bundle_root, bundle_manifest = loaded
    bundle_assets = bundle_manifest.get("assets", {})
    installed: list[str] = []
    warnings: list[str] = []

    for entry in _load_static_model_catalog().models:
        if entry.availability != "available" or not entry.expected_files:
            continue

        record_value = bundle_assets.get(entry.catalog_id)
        if not isinstance(record_value, dict):
            warnings.append(f"Bundled checkpoint manifest is missing {entry.catalog_id}.")
            continue
        record = dict(record_value)
        record_files = record.get("files")
        records_by_name = (
            {
                str(item.get("filename")): dict(item)
                for item in record_files
                if isinstance(item, dict)
            }
            if isinstance(record_files, list)
            else {str(record.get("filename")): record}
        )

        sources: list[Path] = []
        destinations: list[Path] = []
        file_records: list[dict[str, object]] = []
        invalid = False

        for expected in entry.expected_files:
            file_record = records_by_name.get(expected.filename)
            if not isinstance(file_record, dict):
                warnings.append(
                    "Bundled checkpoint manifest is missing "
                    f"{entry.catalog_id}/{expected.filename}."
                )
                invalid = True
                break
            if (
                file_record.get("filename") != expected.filename
                or file_record.get("sha256") != expected.sha256
                or file_record.get("size_bytes") != expected.size_bytes
            ):
                warnings.append(
                    f"Bundled checkpoint metadata does not match the catalog: "
                    f"{entry.catalog_id}/{expected.filename}."
                )
                invalid = True
                break

            relative_path = str(file_record.get("relative_path") or "")
            source = (bundle_root / relative_path).resolve()
            try:
                source.relative_to(bundle_root.resolve())
            except ValueError:
                warnings.append(
                    f"Bundled checkpoint path escapes its resource root: "
                    f"{entry.catalog_id}/{expected.filename}."
                )
                invalid = True
                break
            if not source.is_file() or source.stat().st_size != expected.size_bytes:
                warnings.append(
                    f"Bundled checkpoint is missing or has the wrong size: "
                    f"{entry.catalog_id}/{expected.filename}."
                )
                invalid = True
                break
            if _sha256(source) != expected.sha256:
                warnings.append(
                    f"Bundled checkpoint checksum failed: {entry.catalog_id}/{expected.filename}."
                )
                invalid = True
                break

            sources.append(source)
            destinations.append(catalog_asset_path(settings, entry.catalog_id, expected.filename))
            file_records.append(
                {
                    "filename": expected.filename,
                    "sha256": expected.sha256,
                    "size_bytes": expected.size_bytes,
                    "source_url": expected.source_url,
                    "revision": file_record.get("revision"),
                }
            )

        if invalid:
            continue

        try:
            current_record = catalog_manifest_record(settings, entry.catalog_id)
        except OSError:
            current_record = None
        current_files = current_record.get("files") if current_record else None
        current_by_name = (
            {str(item.get("filename")): item for item in current_files if isinstance(item, dict)}
            if isinstance(current_files, list)
            else (
                {str(current_record.get("filename")): current_record}
                if current_record is not None
                else {}
            )
        )

        failed = False
        for expected, source, destination in zip(
            entry.expected_files, sources, destinations, strict=True
        ):
            current_file = current_by_name.get(expected.filename)
            ready = (
                destination.is_file()
                and destination.stat().st_size == expected.size_bytes
                and isinstance(current_file, dict)
                and current_file.get("sha256") == expected.sha256
                and current_file.get("size_bytes") == expected.size_bytes
            )
            if ready:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(destination.suffix + ".bundled.part")
            temporary.unlink(missing_ok=True)
            try:
                shutil.copyfile(source, temporary)
                if temporary.stat().st_size != expected.size_bytes:
                    raise OSError("copied checkpoint size does not match the catalog")
                os.replace(temporary, destination)
            except OSError as exc:
                temporary.unlink(missing_ok=True)
                warnings.append(
                    "Could not install bundled checkpoint "
                    f"{entry.catalog_id}/{expected.filename}: {exc}"
                )
                failed = True
                break
        if failed:
            continue

        managed_files = [
            {
                **file_record,
                "relative_path": relative_catalog_asset_path(settings, destination),
            }
            for file_record, destination in zip(file_records, destinations, strict=True)
        ]
        total_size = sum(expected.size_bytes for expected in entry.expected_files)
        write_catalog_manifest_record(
            settings,
            entry.catalog_id,
            {
                "filename": entry.expected_files[0].filename,
                "relative_path": relative_catalog_asset_path(
                    settings,
                    destinations[0] if len(destinations) == 1 else destinations[0].parent,
                ),
                "sha256": entry.expected_files[0].sha256
                if len(entry.expected_files) == 1
                else None,
                "size_bytes": total_size,
                "files": managed_files,
                "provider_version": entry.provider_version,
                "source": "bundled_installer",
                "bundle_catalog_version": bundle_manifest.get("catalog_version"),
            },
        )
        installed.append(entry.catalog_id)

    return installed, warnings


def reconcile_bundled_model_jobs(
    factory: sessionmaker[Session], bundled_catalog_ids: list[str]
) -> None:
    """Close obsolete download jobs for models now supplied by the installer."""

    if not bundled_catalog_ids:
        return
    catalog_ids = set(bundled_catalog_ids)
    with factory() as session:
        jobs = session.scalars(
            select(Job).where(
                Job.job_type == "model_install",
                Job.status.in_(["queued", "running", "cancel_requested", "failed"]),
            )
        )
        changed = False
        for job in jobs:
            catalog_id = str(job.request_json.get("catalog_id") or "")
            if catalog_id not in catalog_ids:
                continue
            job.status = "succeeded"
            job.progress_current = job.progress_total
            job.error_message = None
            job.completed_at = datetime.now(UTC)
            result = dict(job.result_json or {})
            result.update(
                {
                    "stage": "ready",
                    "catalog_id": catalog_id,
                    "source": "bundled_installer",
                    "bytes_downloaded": job.progress_total,
                }
            )
            job.result_json = result
            changed = True
        if changed:
            session.commit()
