"""Catalog installation job creation, verification, removal, and readiness checks."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import Job
from reefvision.domain.errors import ConflictError, ValidationError
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.model_catalog import (
    CatalogReadinessResponse,
    CatalogVerifyResponse,
)
from reefvision.services.model_catalog import ModelCatalogService
from reefvision.storage.catalog_models import (
    catalog_asset_path,
    catalog_manifest_record,
    relative_catalog_asset_path,
    remove_catalog_manifest_record,
    write_catalog_manifest_record,
)


class ModelInstallService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.catalog = ModelCatalogService(session, settings)

    def create_install_job(
        self, project_id: str, catalog_id: str, *, confirmed: bool
    ) -> JobResponse:
        if not confirmed:
            raise ValidationError("Confirm the model license, hardware, and download information")
        entry = self.catalog.get_project_catalog_item(project_id, catalog_id)
        if entry.availability != "available" or entry.selection_kind != "managed_catalog_model":
            raise ValidationError(
                entry.installation_reason or "This model has no validated installer"
            )
        if not entry.expected_files:
            raise ValidationError("Catalog entry is missing its trusted download manifest")
        if entry.installation_state == "Ready":
            raise ConflictError("This catalog model is already installed and ready")
        active = self._active_job(project_id, catalog_id)
        if active is not None:
            return JobResponse.model_validate(active)
        job = Job(
            project_id=project_id,
            job_type="model_install",
            status="queued",
            progress_current=0,
            progress_total=entry.expected_size or 0,
            request_json={
                "catalog_id": catalog_id,
                "confirmed": True,
                "source_type": entry.download_source_type,
            },
            result_json={"stage": "queued"},
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return JobResponse.model_validate(job)

    def _active_job(self, project_id: str, catalog_id: str) -> Job | None:
        jobs = list(
            self.session.scalars(
                select(Job).where(
                    Job.project_id == project_id,
                    Job.job_type == "model_install",
                    Job.status.in_(("queued", "running", "cancel_requested")),
                )
            )
        )
        return next(
            (job for job in jobs if str(job.request_json.get("catalog_id")) == catalog_id),
            None,
        )

    def verify(self, project_id: str, catalog_id: str) -> CatalogVerifyResponse:
        entry = self.catalog.get_project_catalog_item(project_id, catalog_id)
        if not entry.expected_files:
            return CatalogVerifyResponse(
                catalog_id=catalog_id,
                installation_state=entry.installation_state,
                verified=entry.installation_state == "Ready",
                reason=entry.installation_reason,
            )
        expected = entry.expected_files[0]
        path = catalog_asset_path(self.settings, catalog_id, expected.filename)
        if not path.is_file():
            return CatalogVerifyResponse(
                catalog_id=catalog_id,
                installation_state="Corrupted",
                verified=False,
                expected_checksum=expected.sha256,
                path=relative_catalog_asset_path(self.settings, path),
                reason="The managed checkpoint is missing.",
            )
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        actual = digest.hexdigest()
        verified = size == expected.size_bytes and actual == expected.sha256
        if verified:
            previous = catalog_manifest_record(self.settings, catalog_id) or {}
            write_catalog_manifest_record(
                self.settings,
                catalog_id,
                {
                    **previous,
                    "filename": expected.filename,
                    "relative_path": relative_catalog_asset_path(self.settings, path),
                    "sha256": actual,
                    "size_bytes": size,
                    "verified_at": datetime.now(UTC).isoformat(),
                },
            )
        return CatalogVerifyResponse(
            catalog_id=catalog_id,
            installation_state="Ready" if verified else "Corrupted",
            verified=verified,
            expected_checksum=expected.sha256,
            actual_checksum=actual,
            path=relative_catalog_asset_path(self.settings, path),
            reason=None if verified else "Managed checkpoint checksum or size is invalid.",
        )

    def remove(self, project_id: str, catalog_id: str) -> None:
        entry = self.catalog.get_project_catalog_item(project_id, catalog_id)
        active = self._active_job(project_id, catalog_id)
        if active is not None:
            raise ConflictError("Cancel the active installation before removing this model")
        for expected in entry.expected_files:
            catalog_asset_path(self.settings, catalog_id, expected.filename).unlink(missing_ok=True)
        remove_catalog_manifest_record(self.settings, catalog_id)

    def readiness(self, project_id: str, catalog_id: str) -> CatalogReadinessResponse:
        entry = self.catalog.get_project_catalog_item(project_id, catalog_id)
        installed_provider_version: str | None = None
        if entry.provider_id == "ultralytics":
            try:
                installed_provider_version = version("ultralytics")
            except PackageNotFoundError:
                installed_provider_version = None
        return CatalogReadinessResponse(
            catalog_id=catalog_id,
            installation_state=entry.installation_state,
            installation_reason=entry.installation_reason,
            provider_id=entry.provider_id,
            provider_version=installed_provider_version,
            provider_ready=installed_provider_version is not None,
            expected_files_valid=bool(entry.expected_files)
            and all(
                item.size_bytes > 0 and len(item.sha256) == 64 for item in entry.expected_files
            ),
            checked_at=datetime.now(UTC),
        )
