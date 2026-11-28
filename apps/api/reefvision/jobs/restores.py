"""Managed restore-job processing for Milestone 8."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job
from reefvision.domain.errors import ValidationError
from reefvision.storage.backups import (
    BACKUP_COMPLETION_MARKER_FILENAME,
    BACKUP_MANIFEST_FILENAME,
    backup_io_path,
    backup_member_path,
    backup_root_path,
    copy_file_with_sha256,
    discard_restore_staging,
    has_restore_job_receipt,
    hash_file,
    is_profile_local_path,
    restore_metadata_filenames,
    restore_staging_path,
    verify_backup_directory,
    write_restore_metadata,
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
        request = session.scalar(
            update(Job)
            .where(Job.id == job_id, Job.job_type == "restore", Job.status == "queued")
            .values(
                status="running",
                started_at=datetime.now(UTC),
                error_message=None,
                result_json={"stage": "verifying_backup"},
            )
            .returning(Job.request_json)
        )
        if request is None:
            return False
        session.commit()

    backup_id = str(request["backup_id"])
    backup_relative = str(request["backup_path"])
    destination_relative = str(request["destination_path"])
    try:
        discard_restore_staging(settings, job_id)
        backup_root = backup_root_path(settings, backup_relative)
        destination_root = backup_root_path(settings, destination_relative)
        ensure_job_not_cancelled(factory, job_id)
        verification = verify_backup_directory(backup_root, backup_id=backup_id)
        if verification["status"] not in {"valid", "valid_with_warnings"}:
            raise RuntimeError("Restore requires a valid backup verification result")

        manifest = json.loads(
            backup_io_path(backup_root / BACKUP_MANIFEST_FILENAME).read_text(encoding="utf-8")
        )
        full_inventory = manifest.get("file_inventory")
        if not isinstance(full_inventory, list):
            raise RuntimeError("Backup manifest file inventory is missing")
        database_filename = manifest.get("database_filename")
        if not isinstance(database_filename, str) or not database_filename:
            raise RuntimeError("Backup manifest database filename is missing")
        # Older media can contain local coordination or trust state. Verify all media
        # first, then copy only the portable entries to the new profile.
        inventory = []
        local_members = []
        for entry in full_inventory:
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                raise RuntimeError("Backup manifest contains an invalid inventory entry")
            parts = PurePosixPath(entry["path"]).parts
            if parts[:1] == ("data",) and is_profile_local_path(parts[1:]):
                local_members.append(entry["path"])
            else:
                inventory.append(entry)
        receipt_filename, marker_filename = restore_metadata_filenames(inventory, database_filename)
        request = {**request, "restore_receipt_filename": receipt_filename}

        if backup_io_path(destination_root).exists():
            if not has_restore_job_receipt(destination_root, job_id, request):
                raise FileExistsError("The selected restore destination already exists")
            for member in local_members:
                target = _restore_target_path(
                    destination_root, backup_path=member, database_filename=database_filename
                )
                if backup_io_path(target).exists():
                    raise RuntimeError(
                        "The recovery contains profile-local state. Restore to a new destination."
                    )
            # The prior process published the directory before committing the job result.
            _verify_restored_copy(
                destination_root, inventory=inventory, database_filename=database_filename
            )
            if hash_file(destination_root / marker_filename) != hash_file(
                backup_root / BACKUP_COMPLETION_MARKER_FILENAME
            ):
                raise RuntimeError(
                    "The published recovery has a different backup completion marker"
                )
            _finalize_success(
                factory,
                job_id=job_id,
                destination_path=destination_relative,
                restored_count=len(inventory),
                restored_bytes=sum(entry["size_bytes"] for entry in inventory),
                verification_status=verification["status"],
                receipt_filename=receipt_filename,
                marker_filename=marker_filename,
            )
            return True

        staging_root = restore_staging_path(settings, job_id)
        staging_root.mkdir(parents=True)
        _update_job_state(
            factory,
            job_id=job_id,
            stage="restoring_files",
            progress_current=0,
            progress_total=max(len(inventory), 1),
            receipt_filename=receipt_filename,
        )

        restored_count = 0
        restored_bytes = 0
        restored_paths: list[Path] = []
        for entry in inventory:
            ensure_job_not_cancelled(factory, job_id)
            relative_path = entry["path"]
            source = backup_member_path(backup_root, relative_path)
            destination = _restore_target_path(
                staging_root,
                backup_path=relative_path,
                database_filename=database_filename,
            )
            _, size_bytes = copy_file_with_sha256(source, destination, staged=True)
            restored_paths.append(destination.relative_to(staging_root))
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
        write_restore_metadata(
            staging_root,
            receipt_filename,
            marker_filename,
            job_id=job_id,
            request=request,
            completion_source=backup_root / BACKUP_COMPLETION_MARKER_FILENAME,
        )
        _verify_restored_copy(
            staging_root,
            inventory=inventory,
            database_filename=database_filename,
        )
        _publish_restore(staging_root, destination_root, restored_paths)
        _finalize_success(
            factory,
            job_id=job_id,
            destination_path=destination_relative,
            restored_count=restored_count,
            restored_bytes=restored_bytes,
            verification_status=verification["status"],
            receipt_filename=receipt_filename,
            marker_filename=marker_filename,
        )
        LOGGER.info(
            "ReefVision restore completed",
            extra={"event_id": "restore_complete", "component": "restore", "job_id": job_id},
        )
        return True
    except JobCancelled:
        _finalize_cancel(factory, job_id=job_id)
        LOGGER.info(
            "ReefVision restore cancelled",
            extra={"event_id": "restore_cancelled", "component": "restore", "job_id": job_id},
        )
        return False
    except Exception as exc:
        _finalize_failure(factory, job_id=job_id, message=str(exc))
        LOGGER.exception(
            "ReefVision restore failed",
            extra={"event_id": "restore_failed", "component": "restore", "job_id": job_id},
        )
        return False
    finally:
        try:
            discard_restore_staging(settings, job_id)
        except (OSError, ValidationError, ValueError):
            LOGGER.exception("Could not clean private staging for restore job %s", job_id)


def recover_cancel_requested_restore(settings: Settings, job: Job) -> None:
    try:
        name = job.request_json.get("destination_path")
        if isinstance(name, str):
            destination = backup_root_path(settings, name)
            if has_restore_job_receipt(destination, job.id, job.request_json):
                # Startup will requeue the published recovery for checksum verification.
                job.status = "running"
                return
        discard_restore_staging(settings, job.id)
    except (OSError, ValidationError, ValueError, KeyError):
        LOGGER.exception("Could not inspect the interrupted restore job %s", job.id)


def _publish_restore(
    staging_root: Path, destination_root: Path, restored_paths: list[Path]
) -> None:
    destination = backup_io_path(destination_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError("The selected restore destination already exists")
    staging = backup_io_path(staging_root)
    staging.rename(destination)
    try:
        # The staging hashes have already been checked. Opening without reading
        # checks that the final path is accessible with the same managed I/O.
        for relative in restored_paths:
            with (destination / relative).open("rb"):
                pass
    except OSError as exc:
        destination.rename(staging)
        raise RuntimeError(
            "Restored files could not be opened at the selected recovery location. "
            "Check that the location is accessible or try a shorter recovery name."
        ) from exc


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
        return backup_member_path(restore_root, database_filename)
    if relative.parts[:1] != ("data",):
        raise RuntimeError(f"Backup inventory entry is not restorable: {backup_path}")
    return backup_member_path(restore_root, relative.relative_to("data").as_posix())


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


def _update_job_state(
    factory: sessionmaker[Session],
    *,
    job_id: str,
    stage: str,
    progress_current: int,
    progress_total: int,
    bytes_processed: int | None = None,
    receipt_filename: str | None = None,
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
        if receipt_filename is not None:
            # Startup cancellation recovery must find the job's own published receipt.
            job.request_json = {**job.request_json, "restore_receipt_filename": receipt_filename}
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
    receipt_filename: str,
    marker_filename: str,
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
            "restore_receipt_filename": receipt_filename,
            "completion_marker_filename": marker_filename,
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
