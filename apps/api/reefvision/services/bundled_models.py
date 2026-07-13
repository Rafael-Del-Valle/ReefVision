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
        if (
            payload.get("manifest_version") == BUNDLE_MANIFEST_VERSION
            and isinstance(payload.get("assets"), dict)
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
        expected = entry.expected_files[0]
        record_value = bundle_assets.get(entry.catalog_id)
        if not isinstance(record_value, dict):
            warnings.append(f"Bundled checkpoint manifest is missing {entry.catalog_id}.")
            continue
        record = dict(record_value)
        relative_path = str(record.get("relative_path") or "")
        source = (bundle_root / relative_path).resolve()
        try:
            source.relative_to(bundle_root.resolve())
        except ValueError:
            warnings.append(f"Bundled checkpoint path escapes its resource root: {entry.catalog_id}.")
            continue
        if (
            record.get("filename") != expected.filename
            or record.get("sha256") != expected.sha256
            or record.get("size_bytes") != expected.size_bytes
        ):
            warnings.append(f"Bundled checkpoint metadata does not match the catalog: {entry.catalog_id}.")
            continue
        if not source.is_file() or source.stat().st_size != expected.size_bytes:
            warnings.append(f"Bundled checkpoint is missing or has the wrong size: {entry.catalog_id}.")
            continue

        destination = catalog_asset_path(settings, entry.catalog_id, expected.filename)
        current_record = None
        try:
            from reefvision.storage.catalog_models import catalog_manifest_record

            current_record = catalog_manifest_record(settings, entry.catalog_id)
        except OSError:
            current_record = None
        destination_ready = (
            destination.is_file()
            and destination.stat().st_size == expected.size_bytes
            and current_record is not None
            and current_record.get("sha256") == expected.sha256
        )
        if not destination_ready:
            if _sha256(source) != expected.sha256:
                warnings.append(f"Bundled checkpoint checksum failed: {entry.catalog_id}.")
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
                warnings.append(f"Could not install bundled checkpoint {entry.catalog_id}: {exc}")
                continue

        write_catalog_manifest_record(
            settings,
            entry.catalog_id,
            {
                "filename": expected.filename,
                "relative_path": relative_catalog_asset_path(settings, destination),
                "sha256": expected.sha256,
                "size_bytes": expected.size_bytes,
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
