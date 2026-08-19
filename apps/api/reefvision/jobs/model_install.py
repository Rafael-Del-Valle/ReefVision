"""Background installation of allow-listed catalog model assets."""

from __future__ import annotations

import hashlib
import os
import shutil
import urllib.request
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from typing import Any, cast

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job
from reefvision.services.model_catalog import ModelCatalogService
from reefvision.storage.catalog_models import (
    catalog_asset_path,
    catalog_model_directories,
    relative_catalog_asset_path,
    write_catalog_manifest_record,
)

CHUNK_SIZE = 1024 * 1024


def _set_job(
    factory: sessionmaker[Session],
    job_id: str,
    *,
    status: str | None = None,
    stage: str | None = None,
    progress: int | None = None,
    error: str | None = None,
    completed: bool = False,
    result: dict[str, object] | None = None,
) -> Job | None:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            return None
        if status is not None:
            job.status = status
        if progress is not None:
            job.progress_current = progress
        if error is not None or status == "succeeded":
            job.error_message = error
        current = dict(job.result_json or {})
        if stage is not None:
            current["stage"] = stage
        if result:
            current.update(result)
        job.result_json = current
        if completed:
            job.completed_at = datetime.now(UTC)
        session.commit()
        session.refresh(job)
        return job


def _cancel_requested(factory: sessionmaker[Session], job_id: str) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        return job is None or job.status == "cancel_requested"


def _fail(factory: sessionmaker[Session], job_id: str, message: str) -> None:
    _set_job(factory, job_id, status="failed", error=message, completed=True)


def _cancel(factory: sessionmaker[Session], job_id: str) -> None:
    _set_job(
        factory,
        job_id,
        status="cancelled",
        stage="cancelled",
        error=None,
        completed=True,
    )


def process_model_install_job(
    settings: Settings, factory: sessionmaker[Session], job_id: str
) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != "model_install" or job.status != "queued":
            return False
        project_id = job.project_id
        catalog_id = str(job.request_json.get("catalog_id") or "")
        if not project_id or not catalog_id:
            job.status = "failed"
            job.error_message = "Model installation job is missing project or catalog identity"
            job.completed_at = datetime.now(UTC)
            session.commit()
            return False
        entry = ModelCatalogService(session, settings).get_static_catalog_item(catalog_id)
        if entry.availability != "available" or entry.selection_kind != "managed_catalog_model":
            job.status = "failed"
            job.error_message = "This catalog entry does not have a validated installer"
            job.completed_at = datetime.now(UTC)
            session.commit()
            return False
        expected_files = entry.expected_files

        # A model install can be offered to both the long-lived worker and the
        # request-triggered fallback thread. Claim it atomically so only one
        # executor can download and finalize the checkpoint.
        claim = cast(
            CursorResult[Any],
            session.execute(
                update(Job)
                .where(Job.id == job_id, Job.status == "queued")
                .values(
                    status="running",
                    started_at=datetime.now(UTC),
                    error_message=None,
                    progress_total=entry.expected_size or 0,
                    result_json={"stage": "downloading", "files_total": len(expected_files)},
                )
            ),
        )
        if int(claim.rowcount or 0) != 1:
            session.rollback()
            return False
        session.commit()

    directories = catalog_model_directories(settings)
    temporary_root = directories["temporary_downloads"] / job_id
    destinations = [
        catalog_asset_path(settings, catalog_id, expected.filename) for expected in expected_files
    ]
    shutil.rmtree(temporary_root, ignore_errors=True)
    temporary_root.mkdir(parents=True, exist_ok=False)
    downloaded_total = 0
    verified_files: list[dict[str, object]] = []
    try:
        for file_index, expected in enumerate(expected_files, start=1):
            temporary = temporary_root / expected.filename
            digest = hashlib.sha256()
            downloaded = 0
            request = urllib.request.Request(
                expected.source_url,
                headers={"User-Agent": f"ReefVision/{entry.provider_version} model-installer"},
            )
            with (
                urllib.request.urlopen(request, timeout=30) as response,
                temporary.open("xb") as output,
            ):
                while chunk := response.read(CHUNK_SIZE):
                    if _cancel_requested(factory, job_id):
                        _cancel(factory, job_id)
                        return False
                    output.write(chunk)
                    digest.update(chunk)
                    downloaded += len(chunk)
                    downloaded_total += len(chunk)
                    _set_job(
                        factory,
                        job_id,
                        stage="downloading",
                        progress=downloaded_total,
                        result={
                            "bytes_downloaded": downloaded_total,
                            "file_index": file_index,
                            "filename": expected.filename,
                        },
                    )
                output.flush()
                os.fsync(output.fileno())
            _set_job(factory, job_id, stage="verifying", progress=downloaded_total)
            actual_sha256 = digest.hexdigest()
            if downloaded != expected.size_bytes:
                raise RuntimeError(
                    f"Downloaded size mismatch for {expected.filename}: "
                    f"expected {expected.size_bytes}, received {downloaded}"
                )
            if actual_sha256 != expected.sha256:
                raise RuntimeError(
                    f"Checksum mismatch for {expected.filename}: "
                    f"expected {expected.sha256}, received {actual_sha256}"
                )
            verified_files.append(
                {
                    "filename": expected.filename,
                    "sha256": actual_sha256,
                    "size_bytes": downloaded,
                    "source_url": expected.source_url,
                    "revision": expected.revision,
                }
            )

        _set_job(factory, job_id, stage="finalizing", progress=downloaded_total)
        for expected, destination in zip(expected_files, destinations, strict=True):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.unlink(missing_ok=True)
            os.replace(temporary_root / expected.filename, destination)
        provider_version: str | None
        try:
            distribution = {
                "ultralytics": "ultralytics",
                "depth_anything_v2": "transformers",
            }.get(entry.provider_id)
            provider_version = version(distribution) if distribution else None
        except PackageNotFoundError:
            provider_version = None
        write_catalog_manifest_record(
            settings,
            catalog_id,
            {
                "filename": expected_files[0].filename,
                "relative_path": relative_catalog_asset_path(
                    settings,
                    destinations[0] if len(destinations) == 1 else destinations[0].parent,
                ),
                "sha256": verified_files[0]["sha256"] if len(verified_files) == 1 else None,
                "size_bytes": downloaded_total,
                "files": [
                    {
                        **record,
                        "relative_path": relative_catalog_asset_path(settings, destination),
                    }
                    for record, destination in zip(verified_files, destinations, strict=True)
                ],
                "source_url": (expected_files[0].source_url if len(expected_files) == 1 else None),
                "revision": expected_files[0].revision,
                "provider_id": entry.provider_id,
                "provider_version": provider_version,
                "verified_at": datetime.now(UTC).isoformat(),
            },
        )
        final_stage = "ready" if provider_version is not None else "provider_required"
        _set_job(
            factory,
            job_id,
            status="succeeded",
            stage=final_stage,
            progress=downloaded_total,
            completed=True,
            result={
                "catalog_id": catalog_id,
                "asset_id": f"catalog_model:{catalog_id}",
                "relative_path": relative_catalog_asset_path(
                    settings,
                    destinations[0] if len(destinations) == 1 else destinations[0].parent,
                ),
                "files": verified_files,
                "sha256": verified_files[0]["sha256"] if len(verified_files) == 1 else None,
                "size_bytes": downloaded_total,
                "provider_version": provider_version,
            },
        )
        return True
    except Exception as exc:
        for destination in destinations:
            destination.unlink(missing_ok=True)
        _fail(factory, job_id, str(exc))
        return False
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)
