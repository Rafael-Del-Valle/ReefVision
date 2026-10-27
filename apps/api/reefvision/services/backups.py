"""Milestone 8 backup history and verification services."""

from __future__ import annotations

import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.orm import Session

from reefvision import __version__
from reefvision.config import Settings
from reefvision.db.models import BackupRecord, Job
from reefvision.domain.errors import ConflictError, NotFoundError
from reefvision.repositories.backups import BackupRepository
from reefvision.repositories.jobs import JobRepository
from reefvision.schemas.backups import (
    BackupCreateRequest,
    BackupCreateResponse,
    BackupRecordResponse,
    BackupRestoreRequest,
    BackupRestoreResponse,
    BackupVerificationResponse,
)
from reefvision.schemas.jobs import JobResponse
from reefvision.storage.backups import (
    BACKUP_FORMAT_VERSION,
    backup_root_path,
    build_backup_plan,
    default_backup_paths,
    resolve_database_path,
    verify_backup_directory,
)


class BackupService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.backups = BackupRepository(session)
        self.jobs = JobRepository(session)

    def list_backups(self) -> list[BackupRecordResponse]:
        return [BackupRecordResponse.model_validate(item) for item in self.backups.list_all()]

    def get_backup(self, backup_id: str) -> BackupRecordResponse:
        return BackupRecordResponse.model_validate(self._backup(backup_id))

    def create_backup(self, payload: BackupCreateRequest) -> BackupCreateResponse:
        if self.jobs.has_active_jobs():
            raise ConflictError(
                "Backups require an idle background queue; wait for current jobs to finish first"
            )

        database_path = resolve_database_path(self.settings)
        plan = build_backup_plan(
            self.settings,
            database_path=database_path,
            include_exports=payload.include_exports,
            include_logs=payload.include_logs,
        )
        created_at = datetime.now(UTC)
        backup_id = str(uuid4())
        destination_path, staging_path, manifest_path, completion_path = default_backup_paths(
            backup_id,
            created_at_label=created_at.strftime("%Y%m%dT%H%M%SZ"),
            database_filename=plan.database_filename,
        )
        job = Job(
            id=str(uuid4()),
            project_id=None,
            job_type="backup",
            status="queued",
            progress_total=max(plan.estimated_file_count, 1),
            request_json={
                "backup_id": backup_id,
                "include_exports": payload.include_exports,
                "include_logs": payload.include_logs,
            },
            result_json={
                "stage": "queued",
                "estimated_file_count": plan.estimated_file_count,
                "estimated_total_size_bytes": plan.estimated_total_size_bytes,
            },
        )
        backup = BackupRecord(
            id=backup_id,
            job_id=job.id,
            status="queued",
            format_version=BACKUP_FORMAT_VERSION,
            destination_path=destination_path,
            staging_path=staging_path,
            manifest_path=manifest_path,
            completion_marker_path=completion_path,
            database_filename=plan.database_filename,
            request_json={
                "include_exports": payload.include_exports,
                "include_logs": payload.include_logs,
                "notes": payload.notes,
                "preview": {
                    "included_sections": plan.included_sections,
                    "excluded_sections": plan.excluded_sections,
                    "estimated_file_count": plan.estimated_file_count,
                    "estimated_total_size_bytes": plan.estimated_total_size_bytes,
                },
            },
        )
        self.jobs.add(job)
        # Persist the parent first: without an ORM relationship SQLAlchemy can
        # flush BackupRecord before Job, which violates the SQLite job FK when
        # runtime foreign-key enforcement is enabled. Keep both in one transaction.
        self.session.flush()
        self.backups.add(backup)
        self.session.commit()
        self.session.refresh(job)
        self.session.refresh(backup)
        return BackupCreateResponse(
            backup=BackupRecordResponse.model_validate(backup),
            job=JobResponse.model_validate(job),
        )

    def verify_backup(self, backup_id: str) -> BackupVerificationResponse:
        backup = self._backup(backup_id)
        root = self._backup_root(backup)
        if not root.is_dir():
            raise NotFoundError("Managed backup directory is missing")
        report = verify_backup_directory(root, backup_id=backup.id)
        backup.result_json = {**(backup.result_json or {}), "last_verification": report}
        self.session.commit()
        return BackupVerificationResponse.model_validate(report)

    def restore_backup(
        self,
        backup_id: str,
        payload: BackupRestoreRequest,
    ) -> BackupRestoreResponse:
        if payload.overwrite_existing:
            raise ConflictError(
                "Milestone 8 restore currently only supports new managed recovery locations"
            )
        if self.jobs.has_active_jobs():
            raise ConflictError(
                "Restore requires an idle background queue; wait for current jobs to finish first"
            )

        backup = self._backup(backup_id)
        backup_root = self._backup_root(backup)
        if not backup_root.is_dir():
            raise NotFoundError("Managed backup directory is missing")

        verification = verify_backup_directory(backup_root, backup_id=backup.id)
        if verification["status"] not in {"valid", "valid_with_warnings"}:
            raise ConflictError("Only verified backups can be restored")
        self._assert_restore_compatibility(verification)

        destination_name = self._restore_destination_name(payload.destination_name, backup.id)
        destination_path = f"recoveries/{destination_name}"
        staging_path = f"recoveries/.t/{destination_name}"
        destination_root = backup_root_path(self.settings, destination_path)
        if destination_root.exists():
            raise ConflictError("The selected restore destination already exists")

        total_size_bytes = verification.get("total_size_bytes")
        if isinstance(total_size_bytes, int):
            free_bytes = shutil.disk_usage(self.settings.resolved_data_dir).free
            if free_bytes < total_size_bytes:
                raise ConflictError(
                    "The ReefVision data directory does not have enough free space for this restore"
                )

        job = Job(
            id=str(uuid4()),
            project_id=None,
            job_type="restore",
            status="queued",
            progress_total=max(int(verification.get("file_count") or 0), 1),
            request_json={
                "backup_id": backup.id,
                "backup_path": backup.destination_path,
                "staging_path": staging_path,
                "destination_path": destination_path,
                "warnings": verification["warnings"],
            },
            result_json={"stage": "queued"},
        )
        self.jobs.add(job)
        self.session.commit()
        self.session.refresh(job)
        return BackupRestoreResponse(
            backup_id=backup.id,
            destination_path=destination_path,
            verification_status=verification["status"],
            warnings=[str(item) for item in verification["warnings"]],
            job=JobResponse.model_validate(job),
        )

    def _backup(self, backup_id: str) -> BackupRecord:
        backup = self.backups.get(backup_id)
        if backup is None:
            raise NotFoundError("Backup not found")
        return backup

    def _backup_root(self, backup: BackupRecord) -> Path:
        return backup_root_path(self.settings, backup.destination_path)

    def _restore_destination_name(self, requested_name: str | None, backup_id: str) -> str:
        if requested_name:
            slug = re.sub(r"[^A-Za-z0-9._-]+", "-", requested_name).strip(".-").lower()
            if not slug:
                raise ConflictError("Restore destination name must contain letters or numbers")
            return slug
        return f"restore-{backup_id[:8]}"

    def _assert_restore_compatibility(self, verification: dict[str, object]) -> None:
        application_version = verification.get("application_version")
        if isinstance(application_version, str) and (
            self._version_tuple(application_version) > self._version_tuple(__version__)
        ):
            raise ConflictError(
                "This backup was created by a newer ReefVision build and "
                "cannot be restored safely here"
            )
        schema_revision = verification.get("current_schema_revision")
        if schema_revision is None:
            return
        if not isinstance(schema_revision, str):
            raise ConflictError("The backup schema revision is invalid")
        if schema_revision not in self._known_schema_revisions():
            raise ConflictError(
                "This backup uses an unsupported database schema revision "
                f"for ReefVision {__version__}"
            )

    def _known_schema_revisions(self) -> set[str]:
        api_root = Path(__file__).resolve().parents[2]
        config = Config(str(api_root / "alembic.ini"))
        config.attributes["configure_logger"] = False
        config.set_main_option("script_location", str(api_root / "migrations"))
        script = ScriptDirectory.from_config(config)
        head = script.get_current_head()
        if head is None:
            return set()
        return {
            revision.revision
            for revision in script.walk_revisions(base="base", head=head)
            if revision.revision is not None
        }

    def _version_tuple(self, value: str) -> tuple[int, ...]:
        pieces = []
        for part in value.split("."):
            try:
                pieces.append(int(part))
            except ValueError:
                pieces.append(0)
        return tuple(pieces)
