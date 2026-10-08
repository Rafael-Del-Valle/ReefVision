"""Catalog installation job creation, verification, removal, and readiness checks."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import Job
from reefvision.domain.errors import ValidationError
from reefvision.ml.optional_transformers_runtime import (
    OPTIONAL_MODEL_SPECS,
    optional_model_status,
)
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.model_catalog import (
    CatalogExpectedFile,
    CatalogReadinessResponse,
    CatalogVerifyResponse,
)
from reefvision.services.model_catalog import ModelCatalogService
from reefvision.storage.catalog_models import (
    catalog_asset_path,
    catalog_manifest_record,
    relative_catalog_asset_path,
    write_catalog_manifest_record,
)


def _sha256_and_size(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


class ModelInstallService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.catalog = ModelCatalogService(session, settings)

    def create_install_job(
        self, project_id: str, catalog_id: str, *, confirmed: bool
    ) -> JobResponse:
        self.catalog.get_project_catalog_item(project_id, catalog_id)
        raise ValidationError(
            "Model downloads are disabled. Train from an architecture or register "
            "a compatible local model."
        )

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
        if entry.provider_id in OPTIONAL_MODEL_SPECS:
            spec = OPTIONAL_MODEL_SPECS[entry.provider_id]
            status = optional_model_status(self.settings, entry.provider_id)
            path = Path(str(status["path"])) / spec.weight_filename
            actual_checksum: str | None = None
            verified = bool(status["verified"]) and path.is_file()
            if path.is_file():
                actual_checksum, _ = _sha256_and_size(path)
                verified = verified and (
                    spec.weight_sha256 is None or actual_checksum == spec.weight_sha256
                )
            state = (
                "Ready"
                if verified and status["transformers_version"]
                else "Provider Required"
                if verified
                else "Corrupted"
            )
            return CatalogVerifyResponse(
                catalog_id=catalog_id,
                installation_state=state,
                verified=verified,
                expected_checksum=spec.weight_sha256,
                actual_checksum=actual_checksum,
                path=str(status["path"]) if status["cached"] else None,
                reason=None
                if verified
                else status["reason"] or "Optional model verification failed.",
            )

        if not entry.expected_files:
            return CatalogVerifyResponse(
                catalog_id=catalog_id,
                installation_state=entry.installation_state,
                verified=entry.installation_state == "Ready",
                reason=entry.installation_reason,
            )
        missing = next(
            (
                expected
                for expected in entry.expected_files
                if not catalog_asset_path(self.settings, catalog_id, expected.filename).is_file()
            ),
            None,
        )
        first = entry.expected_files[0]
        first_path = catalog_asset_path(self.settings, catalog_id, first.filename)
        if missing is not None:
            return CatalogVerifyResponse(
                catalog_id=catalog_id,
                installation_state="Corrupted",
                verified=False,
                expected_checksum=missing.sha256,
                path=relative_catalog_asset_path(
                    self.settings,
                    catalog_asset_path(self.settings, catalog_id, missing.filename),
                ),
                reason=f"The managed model file {missing.filename} is missing.",
            )
        records: list[dict[str, object]] = []
        invalid: tuple[CatalogExpectedFile, str, int] | None = None
        for expected in entry.expected_files:
            path = catalog_asset_path(self.settings, catalog_id, expected.filename)
            actual, size = _sha256_and_size(path)
            records.append(
                {
                    "filename": expected.filename,
                    "relative_path": relative_catalog_asset_path(self.settings, path),
                    "sha256": actual,
                    "size_bytes": size,
                }
            )
            if size != expected.size_bytes or actual != expected.sha256:
                invalid = (expected, actual, size)
                break
        verified = invalid is None
        if verified:
            previous = catalog_manifest_record(self.settings, catalog_id) or {}
            write_catalog_manifest_record(
                self.settings,
                catalog_id,
                {
                    **previous,
                    "filename": first.filename,
                    "relative_path": relative_catalog_asset_path(
                        self.settings,
                        first_path if len(records) == 1 else first_path.parent,
                    ),
                    "sha256": first.sha256 if len(records) == 1 else None,
                    "size_bytes": sum(item.size_bytes for item in entry.expected_files),
                    "files": records,
                    "verified_at": datetime.now(UTC).isoformat(),
                },
            )
        failed_expected = invalid[0] if invalid else None
        return CatalogVerifyResponse(
            catalog_id=catalog_id,
            installation_state="Ready" if verified else "Corrupted",
            verified=verified,
            expected_checksum=failed_expected.sha256 if failed_expected else None,
            actual_checksum=invalid[1] if invalid else None,
            path=relative_catalog_asset_path(
                self.settings,
                first_path if len(records) == 1 else first_path.parent,
            ),
            reason=None if verified else "Managed checkpoint checksum or size is invalid.",
        )

    def remove(self, project_id: str, catalog_id: str) -> None:
        self.catalog.get_project_catalog_item(project_id, catalog_id)
        raise ValidationError(
            "Catalog removal is disabled. Registered models are managed separately; "
            "legacy cache cleanup requires a provenance-verified preview."
        )

    def readiness(self, project_id: str, catalog_id: str) -> CatalogReadinessResponse:
        entry = self.catalog.get_project_catalog_item(project_id, catalog_id)
        installed_provider_version: str | None = None
        distribution = {
            "ultralytics": "ultralytics",
            "depth_anything_v2": "transformers",
            "grounding_dino": "transformers",
            "sam2": "transformers",
            "smolvlm": "transformers",
            "scale_label_ocr": "transformers",
        }.get(entry.provider_id)
        if distribution is not None:
            try:
                installed_provider_version = version(distribution)
            except PackageNotFoundError:
                installed_provider_version = None
        return CatalogReadinessResponse(
            catalog_id=catalog_id,
            installation_state=entry.installation_state,
            installation_reason=entry.installation_reason,
            provider_id=entry.provider_id,
            provider_version=installed_provider_version,
            provider_ready=installed_provider_version is not None,
            expected_files_valid=(
                entry.provider_id in OPTIONAL_MODEL_SPECS
                or (
                    bool(entry.expected_files)
                    and all(
                        item.size_bytes > 0 and len(item.sha256) == 64
                        for item in entry.expected_files
                    )
                )
            ),
            checked_at=datetime.now(UTC),
        )
