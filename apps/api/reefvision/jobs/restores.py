"""Managed restore-job processing for Milestone 8."""

from __future__ import annotations

import json
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job
from reefvision.storage.backups import (
    BACKUP_COMPLETION_MARKER_FILENAME,
    BACKUP_MANIFEST_FILENAME,
    backup_root_path,
    copy_file_with_sha256,
    hash_file,
    verify_backup_directory,
)

LOGGER = logging.getLogger("reefvision.restores")


class JobCancelled(Exception):
    """Raised when a queued or running job is cancelled."""


def ensure_job_not_cancelled(factory: sessionmaker[Session], job_id: str) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is not None and job.status == "cancel_requested":
            raise JobCancelled()


def process_restore_job(settings: Settings, factory: sessionmaker[Session], job_id: str) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != "restore" or job.status != "queued":
            return False
        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.error_message = None
        job.result_json = {"stage": "verifying_backup"}
        session.commit()
        request = dict(job.request_json)

    backup_id = str(request["backup_id"])
    backup_relative = str(request["backup_path"])
    staging_relative = str(request["staging_path"])
    destination_relative = str(request["destination_path"])
    backup_root = backup_root_path(settings, backup_relative)
    staging_root = backup_root_path(settings, staging_relative)
    destination_root = backup_root_path(settings, destination_relative)

    try:
        ensure_job_not_cancelled(factory, job_id)
        verification = verify_backup_directory(backup_root, backup_id=backup_id)
        if verification["status"] not in {"valid", "valid_with_warnings"}:
            raise RuntimeError("Restore requires a valid backup verification result")

        shutil.rmtree(staging_root, ignore_errors=True)
        if destination_root.exists():
            raise FileExistsError("The selected restore destination already exists")
        staging_root.mkdir(parents=True, exist_ok=False)

        manifest = json.loads((backup_root / BACKUP_MANIFEST_FILENAME).read_text(encoding="utf-8"))
        inventory = manifest.get("file_inventory")
        if not isinstance(inventory, list):
            raise RuntimeError("Backup manifest file inventory is missing")
        database_filename = manifest.get("database_filename")
        if not isinstance(database_filename, str) or not database_filename:
            raise RuntimeError("Backup manifest database filename is missing")

        _update_job_state(
            factory,
            job_id=job_id,
            stage="restoring_files",
            progress_current=0,
            progress_total=max(len(inventory), 1),
        )

        restored_count = 0
        restored_bytes = 0
        for entry in inventory:
            ensure_job_not_cancelled(factory, job_id)
            if not isinstance(entry, dict):
                raise RuntimeError("Backup manifest contains an invalid inventory entry")
            relative_path = entry.get("path")
            if not isinstance(relative_path, str):
                raise RuntimeError("Backup manifest path entry is invalid")
            source = backup_root / PurePosixPath(relative_path)
            destination = _restore_target_path(
                staging_root,
                backup_path=relative_path,
                database_filename=database_filename,
            )
            _, size_bytes = copy_file_with_sha256(source, destination)
            restored_count += 1
            restored_bytes += size_bytes
            _update_job_state(
                factory,
                job_id=job_id,
                stage="restoring_files",
                progress_current=restored_count,
                progress_total=len(inventory),
                bytes_processed=restored_bytes,
            )

        ensure_job_not_cancelled(factory, job_id)
        _write_restore_receipt(
            staging_root,
            backup_id=backup_id,
            backup_relative=backup_relative,
            destination_relative=destination_relative,
        )
        _verify_restored_copy(
            staging_root,
            inventory=inventory,
            database_filename=database_filename,
        )
        completion_source = backup_root / BACKUP_COMPLETION_MARKER_FILENAME
        shutil.copy2(completion_source, staging_root / "restored-from-backup-complete.json")
        destination_root.parent.mkdir(parents=True, exist_ok=True)
        staging_root.rename(destination_root)
        _finalize_success(
            factory,
            job_id=job_id,
            destination_path=destination_relative,
            restored_count=restored_count,
            restored_bytes=restored_bytes,
            verification_status=verification["status"],
        )
        LOGGER.info(
            "ReefVision restore completed",
            extra={"event_id": "restore_complete", "component": "restore", "job_id": job_id},
        )
        return True
    except JobCancelled:
        shutil.rmtree(staging_root, ignore_errors=True)
        _finalize_cancel(factory, job_id=job_id)
        LOGGER.info(
            "ReefVision restore cancelled",
            extra={"event_id": "restore_cancelled", "component": "restore", "job_id": job_id},
        )
        return False
    except Exception as exc:
        shutil.rmtree(staging_root, ignore_errors=True)
        _finalize_failure(factory, job_id=job_id, message=str(exc))
        LOGGER.exception(
            "ReefVision restore failed",
            extra={"event_id": "restore_failed", "component": "restore", "job_id": job_id},
        )
        return False


def _restore_target_path(
    restore_root: Path,
    *,
    backup_path: str,
    database_filename: str,
) -> Path:
    relative = PurePosixPath(backup_path)
    if relative.parts[:1] == ("database",):
        if relative.name != database_filename:
            raise RuntimeError("Backup database filename does not match the manifest")
        return restore_root / database_filename
    if relative.parts[:1] != ("data",):
        raise RuntimeError(f"Backup inventory entry is not restorable: {backup_path}")
    return restore_root.joinpath(*relative.parts[1:])


def _verify_restored_copy(
    restore_root: Path,
    *,
    inventory: list[Any],
    database_filename: str,
) -> None:
    for entry in inventory:
        if not isinstance(entry, dict):
            raise RuntimeError("Restored inventory entry is invalid")
        relative_path = entry.get("path")
        expected_sha = entry.get("sha256")
        expected_size = entry.get("size_bytes")
        if (
            not isinstance(relative_path, str)
            or not isinstance(expected_sha, str)
            or not isinstance(expected_size, int)
        ):
            raise RuntimeError("Restored inventory entry is invalid")
        restored_path = _restore_target_path(
            restore_root,
            backup_path=relative_path,
            database_filename=database_filename,
        )
        actual_sha, actual_size = hash_file(restored_path)
        if actual_sha != expected_sha or actual_size != expected_size:
            raise RuntimeError(f"Restored file failed verification: {relative_path}")


def _write_restore_receipt(
    restore_root: Path,
    *,
    backup_id: str,
    backup_relative: str,
    destination_relative: str,
) -> None:
    restore_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "backup_id": backup_id,
        "source_backup_path": backup_relative,
        "restored_destination": destination_relative,
        "restored_at": datetime.now(UTC).isoformat(),
    }
    (restore_root / "restore-receipt.json").write_text(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def _update_job_state(
    factory: sessionmaker[Session],
    *,
    job_id: str,
    stage: str,
    progress_current: int,
    progress_total: int,
    bytes_processed: int | None = None,
) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.progress_current = progress_current
        job.progress_total = progress_total
        result_json: dict[str, Any] = {
            "stage": stage,
        }
        if bytes_processed is not None:
            result_json["bytes_processed"] = bytes_processed
        job.result_json = result_json
        session.commit()


def _finalize_success(
    factory: sessionmaker[Session],
    *,
    job_id: str,
    destination_path: str,
    restored_count: int,
    restored_bytes: int,
    verification_status: str,
) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.status = "succeeded"
        job.progress_current = restored_count
        job.progress_total = restored_count
        job.completed_at = datetime.now(UTC)
        job.result_json = {
            "stage": "completed",
            "destination_path": destination_path,
            "restored_file_count": restored_count,
            "restored_total_size_bytes": restored_bytes,
            "verification_status": verification_status,
        }
        session.commit()


def _finalize_cancel(factory: sessionmaker[Session], *, job_id: str) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.status = "cancelled"
        job.completed_at = datetime.now(UTC)
        job.result_json = {"stage": "cancelled"}
        session.commit()


def _finalize_failure(
    factory: sessionmaker[Session],
    *,
    job_id: str,
    message: str,
) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.status = "failed"
        job.error_message = message
        job.completed_at = datetime.now(UTC)
        job.result_json = {"stage": "failed", "error": message}
        session.commit()
