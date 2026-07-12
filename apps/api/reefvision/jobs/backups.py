"""Managed backup-job processing for Milestone 8."""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from alembic.runtime.migration import MigrationContext
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import (
    Annotation,
    AnnotationEvent,
    BackupRecord,
    DatasetVersion,
    DatasetVersionItem,
    ExportRecord,
    ImageAsset,
    Job,
    LabelClass,
    ModelRegistration,
    PredictionProposal,
    Project,
    QualityControlIssue,
    QualityControlRun,
    ReviewQueue,
    ReviewQueueItem,
)
from reefvision.storage.backups import (
    backup_root_path,
    build_backup_plan,
    build_manifest,
    copy_file_with_sha256,
    create_sqlite_snapshot,
    hash_file,
    resolve_database_path,
    verify_backup_directory,
    write_backup_completion_marker,
    write_backup_manifest,
)

LOGGER = logging.getLogger("reefvision.backups")

COUNT_MODELS: tuple[tuple[str, type[object]], ...] = (
    ("projects", Project),
    ("label_classes", LabelClass),
    ("images", ImageAsset),
    ("annotations", Annotation),
    ("annotation_events", AnnotationEvent),
    ("models", ModelRegistration),
    ("prediction_proposals", PredictionProposal),
    ("dataset_versions", DatasetVersion),
    ("dataset_version_items", DatasetVersionItem),
    ("exports", ExportRecord),
    ("jobs", Job),
    ("quality_control_runs", QualityControlRun),
    ("quality_control_issues", QualityControlIssue),
    ("review_queues", ReviewQueue),
    ("review_queue_items", ReviewQueueItem),
    ("backup_records", BackupRecord),
)


class BackupCancelled(Exception):
    """Raised when a backup job observes a cancellation request."""


def process_backup_job(settings: Settings, factory: sessionmaker[Session], job_id: str) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        backup = session.scalar(select(BackupRecord).where(BackupRecord.job_id == job_id))
        if job is None or backup is None or job.job_type != "backup" or job.status != "queued":
            return False
        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.error_message = None
        job.result_json = {
            **(job.result_json or {}),
            "stage": "preparing",
            "warnings": [],
        }
        backup.status = "running"
        backup.started_at = datetime.now(UTC)
        backup.error_message = None
        session.commit()
        backup_id = backup.id
        request_json = dict(backup.request_json)
        destination_path = backup.destination_path
        staging_path = backup.staging_path
        manifest_relative = backup.manifest_path
        completion_relative = backup.completion_marker_path
        created_at = backup.created_at
        notes = request_json.get("notes")

    assert staging_path is not None
    staging_root = backup_root_path(settings, staging_path)
    final_root = backup_root_path(settings, destination_path)
    manifest_path = backup_root_path(settings, manifest_relative)
    completion_path = backup_root_path(settings, completion_relative)
    staging_manifest_path = staging_root / PurePosixPath("backup-manifest.json")
    staging_completion_path = staging_root / PurePosixPath("backup-complete.json")
    bytes_processed = 0
    warnings: list[str] = []

    try:
        database_path = resolve_database_path(settings)
        plan = build_backup_plan(
            settings,
            database_path=database_path,
            include_exports=bool(request_json.get("include_exports", False)),
            include_logs=bool(request_json.get("include_logs", False)),
        )
        if final_root.exists():
            raise FileExistsError("Managed backup destination already exists")
        shutil.rmtree(staging_root, ignore_errors=True)
        staging_root.mkdir(parents=True, exist_ok=False)

        _update_runtime_state(
            factory,
            backup_id=backup_id,
            job_id=job_id,
            stage="snapshotting",
            progress_current=0,
            progress_total=plan.estimated_file_count,
            bytes_processed=0,
            items_processed=0,
            warnings=warnings,
        )
        LOGGER.info(
            "Starting ReefVision backup",
            extra={"event_id": "backup_start", "component": "backup", "job_id": job_id},
        )
        database_snapshot = staging_root / PurePosixPath(plan.database_backup_path)
        create_sqlite_snapshot(plan.database_source_path, database_snapshot)
        _ensure_not_cancelled(factory, job_id)

        copied_inventory: list[dict[str, Any]] = []
        copied_count = 0
        for candidate in plan.data_files:
            _ensure_not_cancelled(factory, job_id)
            destination = staging_root / PurePosixPath(candidate.backup_path)
            sha256, size_bytes = copy_file_with_sha256(candidate.source_path, destination)
            copied_count += 1
            bytes_processed += size_bytes
            copied_inventory.append(
                {
                    "path": candidate.backup_path,
                    "size_bytes": size_bytes,
                    "sha256": sha256,
                }
            )
            _update_runtime_state(
                factory,
                backup_id=backup_id,
                job_id=job_id,
                stage="copying",
                progress_current=copied_count,
                progress_total=plan.estimated_file_count,
                bytes_processed=bytes_processed,
                items_processed=copied_count,
                warnings=warnings,
            )

        item_counts, current_schema_revision = _database_summary(factory)
        _patch_snapshot_database(database_snapshot, backup_id=backup_id, job_id=job_id)
        database_sha256, database_size = hash_file(database_snapshot)
        copied_count += 1
        bytes_processed += database_size
        file_inventory = [
            {
                "path": plan.database_backup_path,
                "size_bytes": database_size,
                "sha256": database_sha256,
            },
            *copied_inventory,
        ]
        manifest = build_manifest(
            backup_id=backup_id,
            created_at=created_at.isoformat(),
            current_schema_revision=current_schema_revision,
            plan=plan,
            file_inventory=file_inventory,
            item_counts=item_counts,
            notes=notes if isinstance(notes, str) else None,
        )
        manifest_sha256, _ = write_backup_manifest(staging_manifest_path, manifest)
        write_backup_completion_marker(
            staging_completion_path,
            {
                "backup_id": backup_id,
                "backup_format_version": manifest["backup_format_version"],
                "manifest_sha256": manifest_sha256,
                "completed_at": datetime.now(UTC).isoformat(),
            },
        )
        _update_runtime_state(
            factory,
            backup_id=backup_id,
            job_id=job_id,
            stage="verifying",
            progress_current=plan.estimated_file_count,
            progress_total=plan.estimated_file_count,
            bytes_processed=bytes_processed,
            items_processed=plan.estimated_file_count,
            warnings=warnings,
            backup_status="verifying",
        )
        verification = verify_backup_directory(staging_root, backup_id=backup_id)
        if verification["status"] not in {"valid", "valid_with_warnings"}:
            raise RuntimeError(
                "Backup verification failed: "
                + "; ".join(verification["errors"] or verification["checksum_failures"])
            )
        if verification["warnings"]:
            warnings.extend(str(item) for item in verification["warnings"])
        final_root.parent.mkdir(parents=True, exist_ok=True)
        staging_root.rename(final_root)
        _finalize_success(
            factory,
            backup_id=backup_id,
            job_id=job_id,
            result_json={
                "stage": "completed",
                "verification_status": verification["status"],
                "warnings": warnings,
                "file_count": len(file_inventory),
                "total_size_bytes": int(manifest["total_expected_size_bytes"]),
                "manifest_path": str(manifest_path),
                "completion_marker_path": str(completion_path),
                "manifest_sha256": manifest_sha256,
            },
            file_count=len(file_inventory),
            total_size_bytes=int(manifest["total_expected_size_bytes"]),
        )
        LOGGER.info(
            "ReefVision backup completed",
            extra={"event_id": "backup_complete", "component": "backup", "job_id": job_id},
        )
        return True
    except BackupCancelled:
        shutil.rmtree(staging_root, ignore_errors=True)
        _finalize_cancel(factory, backup_id=backup_id, job_id=job_id)
        LOGGER.info(
            "ReefVision backup cancelled",
            extra={"event_id": "backup_cancelled", "component": "backup", "job_id": job_id},
        )
        return False
    except Exception as exc:
        shutil.rmtree(staging_root, ignore_errors=True)
        _finalize_failure(factory, backup_id=backup_id, job_id=job_id, message=str(exc))
        LOGGER.exception(
            "ReefVision backup failed",
            extra={"event_id": "backup_failed", "component": "backup", "job_id": job_id},
        )
        return False


def _ensure_not_cancelled(factory: sessionmaker[Session], job_id: str) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is not None and job.status == "cancel_requested":
            raise BackupCancelled()


def _database_summary(factory: sessionmaker[Session]) -> tuple[dict[str, int], str | None]:
    with factory() as session:
        counts = {
            name: int(session.scalar(select(func.count()).select_from(model)) or 0)
            for name, model in COUNT_MODELS
        }
        revision = MigrationContext.configure(session.connection()).get_current_revision()
        return counts, revision


def _patch_snapshot_database(snapshot_path: Path, *, backup_id: str, job_id: str) -> None:
    connection = sqlite3.connect(snapshot_path)
    try:
        backup_result = json.dumps({"stage": "completed"}, separators=(",", ":"), ensure_ascii=True)
        job_result = json.dumps({"stage": "completed"}, separators=(",", ":"), ensure_ascii=True)
        connection.execute(
            (
                "UPDATE backup_records "
                "SET status = ?, error_message = NULL, result_json = ? WHERE id = ?"
            ),
            ("completed", backup_result, backup_id),
        )
        connection.execute(
            "UPDATE jobs SET status = ?, error_message = NULL, result_json = ? WHERE id = ?",
            ("succeeded", job_result, job_id),
        )
        connection.commit()
    finally:
        connection.close()


def _update_runtime_state(
    factory: sessionmaker[Session],
    *,
    backup_id: str,
    job_id: str,
    stage: str,
    progress_current: int,
    progress_total: int,
    bytes_processed: int,
    items_processed: int,
    warnings: list[str],
    backup_status: str | None = None,
) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        backup = session.get(BackupRecord, backup_id)
        if job is None or backup is None:
            return
        job.progress_current = progress_current
        job.progress_total = progress_total
        job.result_json = {
            "stage": stage,
            "bytes_processed": bytes_processed,
            "items_processed": items_processed,
            "warnings": list(warnings),
        }
        if backup_status is not None:
            backup.status = backup_status
        backup.result_json = {
            "stage": stage,
            "bytes_processed": bytes_processed,
            "items_processed": items_processed,
            "warnings": list(warnings),
        }
        session.commit()


def _finalize_success(
    factory: sessionmaker[Session],
    *,
    backup_id: str,
    job_id: str,
    result_json: dict[str, Any],
    file_count: int,
    total_size_bytes: int,
) -> None:
    completed_at = datetime.now(UTC)
    with factory() as session:
        job = session.get(Job, job_id)
        backup = session.get(BackupRecord, backup_id)
        if job is None or backup is None:
            return
        job.status = "succeeded"
        job.progress_current = file_count
        job.result_json = result_json
        job.completed_at = completed_at
        backup.status = "completed"
        backup.result_json = {**result_json, "total_size_bytes": total_size_bytes}
        backup.completed_at = completed_at
        session.commit()


def _finalize_cancel(factory: sessionmaker[Session], *, backup_id: str, job_id: str) -> None:
    completed_at = datetime.now(UTC)
    with factory() as session:
        job = session.get(Job, job_id)
        backup = session.get(BackupRecord, backup_id)
        if job is None or backup is None:
            return
        job.status = "cancelled"
        job.result_json = {"stage": "cancelled"}
        job.completed_at = completed_at
        backup.status = "cancelled"
        backup.result_json = {"stage": "cancelled"}
        backup.completed_at = completed_at
        session.commit()


def _finalize_failure(
    factory: sessionmaker[Session],
    *,
    backup_id: str,
    job_id: str,
    message: str,
) -> None:
    completed_at = datetime.now(UTC)
    with factory() as session:
        job = session.get(Job, job_id)
        backup = session.get(BackupRecord, backup_id)
        if job is None or backup is None:
            return
        job.status = "failed"
        job.error_message = message
        job.result_json = {"stage": "failed", "error": message}
        job.completed_at = completed_at
        backup.status = "failed"
        backup.error_message = message
        backup.result_json = {"stage": "failed", "error": message}
        backup.completed_at = completed_at
        session.commit()
