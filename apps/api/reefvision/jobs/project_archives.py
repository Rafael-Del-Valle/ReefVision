"""Background processing for complete-project archives and lifecycle operations."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job
from reefvision.storage.project_archives import (
    import_project_archive,
    migrate_project_storage,
    write_project_archive,
)


def _start(
    factory: sessionmaker[Session], job_id: str, expected_type: str
) -> tuple[dict, str | None]:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != expected_type or job.status != "queued":
            return {}, None
        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.heartbeat_at = job.started_at
        job.error_message = None
        job.result_json = {"stage": "running"}
        session.commit()
        return dict(job.request_json), job.project_id


def _success(
    factory: sessionmaker[Session],
    job_id: str,
    result: dict,
    *,
    progress_current: int = 1,
    progress_total: int = 1,
    project_id: str | None = None,
) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.status = "succeeded"
        job.project_id = project_id if project_id is not None else job.project_id
        job.progress_current = progress_current
        job.progress_total = progress_total
        job.completed_at = datetime.now(UTC)
        job.heartbeat_at = job.completed_at
        job.result_json = {"stage": "completed", **result}
        session.commit()


def _failure(factory: sessionmaker[Session], job_id: str, exc: Exception) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.status = "failed"
        job.error_message = str(exc)
        job.completed_at = datetime.now(UTC)
        job.result_json = {"stage": "failed", "error": str(exc)}
        session.commit()


def process_project_archive_export_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    request, project_id = _start(factory, job_id, "project_archive_export")
    if project_id is None:
        return False
    try:
        with factory() as session:
            relative, result = write_project_archive(
                settings,
                session,
                project_id=project_id,
                archive_id=str(request["archive_id"]),
                include_archived_records=bool(request.get("include_archived_records", True)),
                notes=(str(request["notes"]) if request.get("notes") else None),
            )
        _success(factory, job_id, {"archive_path": relative, **result})
        return True
    except Exception as exc:
        _failure(factory, job_id, exc)
        return False


def process_project_archive_import_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    request, marker = _start(factory, job_id, "project_archive_import")
    if marker is not None:
        return False
    try:
        result = import_project_archive(
            settings,
            factory,
            archive_path=str(request["archive_path"]),
            name=(str(request["name"]) if request.get("name") else None),
            slug=(str(request["slug"]) if request.get("slug") else None),
            restore_as_active=bool(request.get("restore_as_active", True)),
        )
        _success(factory, job_id, result, project_id=str(result["project_id"]))
        return True
    except Exception as exc:
        _failure(factory, job_id, exc)
        return False


def process_project_duplicate_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    request, project_id = _start(factory, job_id, "project_duplicate")
    if project_id is None:
        return False
    try:
        archive_id = f"duplicate-{job_id}"
        with factory() as session:
            archive_path, archive_result = write_project_archive(
                settings,
                session,
                project_id=project_id,
                archive_id=archive_id,
                include_archived_records=bool(request.get("include_archived_records", True)),
                notes="Temporary archive created for project duplication.",
            )
        with factory() as session:
            job = session.get(Job, job_id)
            if job is not None:
                job.progress_current = 1
                job.progress_total = 2
                job.heartbeat_at = datetime.now(UTC)
                job.result_json = {
                    "stage": "importing_duplicate",
                    "temporary_archive_path": archive_path,
                }
                session.commit()
        result = import_project_archive(
            settings,
            factory,
            archive_path=archive_path,
            name=str(request["name"]),
            slug=(str(request["slug"]) if request.get("slug") else None),
            restore_as_active=True,
        )
        result["source_project_id"] = project_id
        result["temporary_archive"] = archive_result
        _success(
            factory,
            job_id,
            result,
            progress_current=2,
            progress_total=2,
            project_id=str(result["project_id"]),
        )
        return True
    except Exception as exc:
        _failure(factory, job_id, exc)
        return False


def process_project_storage_migration_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    request, project_id = _start(factory, job_id, "project_storage_migration")
    if project_id is None:
        return False
    try:
        with factory() as session:
            result = migrate_project_storage(
                settings,
                session,
                project_id=project_id,
                destination_relative_path=str(request["destination_relative_path"]),
                mode=str(request.get("mode", "move")),
            )
        _success(factory, job_id, result)
        return True
    except Exception as exc:
        _failure(factory, job_id, exc)
        return False
