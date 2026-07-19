"""Read-only integrity inspection for project records and managed paths."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    ExportRecord,
    ImageAsset,
    Job,
    MaskAnnotation,
    ModelRegistration,
    Project,
    TrainingRun,
    VideoAsset,
)
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.project_integrity import (
    IntegrityResourceKind,
    IntegritySeverity,
    ProjectIntegrityCategorySummary,
    ProjectIntegrityIssue,
    ProjectIntegrityResponse,
)
from reefvision.storage.projects import resolve_managed_project_path

CATEGORY_ORDER: tuple[IntegrityResourceKind, ...] = (
    "project_root",
    "image",
    "thumbnail",
    "raster_mask",
    "model",
    "export_output",
    "export_manifest",
    "export_archive",
    "training_log",
    "training_checkpoint",
    "video",
    "job",
)


@dataclass
class _CategoryAccumulator:
    resource_kind: IntegrityResourceKind
    record_count: int = 0
    referenced_file_count: int = 0
    existing_file_count: int = 0
    missing_file_count: int = 0
    total_existing_bytes: int = 0
    checksum_verified_count: int = 0
    checksum_mismatch_count: int = 0

    def response(self) -> ProjectIntegrityCategorySummary:
        return ProjectIntegrityCategorySummary(
            resource_kind=self.resource_kind,
            record_count=self.record_count,
            referenced_file_count=self.referenced_file_count,
            existing_file_count=self.existing_file_count,
            missing_file_count=self.missing_file_count,
            total_existing_bytes=self.total_existing_bytes,
            checksum_verified_count=self.checksum_verified_count,
            checksum_mismatch_count=self.checksum_mismatch_count,
        )


class ProjectIntegrityService:
    """Inspect database-to-filesystem consistency without mutating project data."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.categories = {kind: _CategoryAccumulator(kind) for kind in CATEGORY_ORDER}
        self.issues: list[ProjectIntegrityIssue] = []
        self.verify_checksums = False

    def _project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    @staticmethod
    def _file_checksum(path: Path) -> str:
        digest = sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _path_size(path: Path) -> int:
        if path.is_file():
            return path.stat().st_size
        return sum(child.stat().st_size for child in path.rglob("*") if child.is_file())

    def _issue(
        self,
        *,
        severity: IntegritySeverity,
        code: str,
        resource_kind: IntegrityResourceKind,
        message: str,
        record_id: str | None = None,
        managed_path: str | None = None,
        repairable: bool = False,
    ) -> None:
        self.issues.append(
            ProjectIntegrityIssue(
                severity=severity,
                code=code,
                resource_kind=resource_kind,
                record_id=record_id,
                managed_path=managed_path,
                message=message,
                repairable=repairable,
            )
        )

    def _inspect_path(
        self,
        *,
        resource_kind: IntegrityResourceKind,
        record_id: str,
        managed_path: str,
        expected_kind: str,
        expected_sha256: str | None = None,
        missing_severity: IntegritySeverity = "error",
        repairable: bool = False,
    ) -> None:
        category = self.categories[resource_kind]
        category.referenced_file_count += 1
        try:
            path = resolve_managed_project_path(self.settings, managed_path)
        except ValidationError:
            category.missing_file_count += 1
            self._issue(
                severity="error",
                code="managed_path_escape",
                resource_kind=resource_kind,
                record_id=record_id,
                managed_path=managed_path,
                message="Stored managed path escapes the ReefVision data directory.",
            )
            return
        if not path.exists():
            category.missing_file_count += 1
            self._issue(
                severity=missing_severity,
                code="managed_path_missing",
                resource_kind=resource_kind,
                record_id=record_id,
                managed_path=managed_path,
                message="The database record references a managed path that is missing.",
                repairable=repairable,
            )
            return
        kind_matches = (
            expected_kind == "either"
            or (expected_kind == "file" and path.is_file())
            or (expected_kind == "directory" and path.is_dir())
        )
        if not kind_matches:
            category.missing_file_count += 1
            self._issue(
                severity="error",
                code="managed_path_type_mismatch",
                resource_kind=resource_kind,
                record_id=record_id,
                managed_path=managed_path,
                message=(f"The managed path exists but is not the expected {expected_kind} type."),
            )
            return
        category.existing_file_count += 1
        category.total_existing_bytes += self._path_size(path)
        if self.verify_checksums and expected_sha256:
            if not path.is_file():
                self._issue(
                    severity="error",
                    code="checksum_target_not_file",
                    resource_kind=resource_kind,
                    record_id=record_id,
                    managed_path=managed_path,
                    message="A checksum can only be verified against a regular file.",
                )
                return
            category.checksum_verified_count += 1
            actual = self._file_checksum(path)
            if actual.casefold() != expected_sha256.casefold():
                category.checksum_mismatch_count += 1
                self._issue(
                    severity="error",
                    code="checksum_mismatch",
                    resource_kind=resource_kind,
                    record_id=record_id,
                    managed_path=managed_path,
                    message=(
                        "The managed file checksum does not match the immutable "
                        "checksum stored in the database."
                    ),
                )

    def _inspect_file(
        self,
        *,
        resource_kind: IntegrityResourceKind,
        record_id: str,
        managed_path: str,
        expected_sha256: str | None = None,
        missing_severity: IntegritySeverity = "error",
        repairable: bool = False,
    ) -> None:
        self._inspect_path(
            resource_kind=resource_kind,
            record_id=record_id,
            managed_path=managed_path,
            expected_kind="file",
            expected_sha256=expected_sha256,
            missing_severity=missing_severity,
            repairable=repairable,
        )

    def _inspect_directory(
        self,
        *,
        resource_kind: IntegrityResourceKind,
        record_id: str,
        managed_path: str,
    ) -> None:
        self._inspect_path(
            resource_kind=resource_kind,
            record_id=record_id,
            managed_path=managed_path,
            expected_kind="directory",
        )

    def _inspect_project_root(self, project: Project) -> None:
        category = self.categories["project_root"]
        category.record_count = 1
        try:
            root = resolve_managed_project_path(self.settings, project.storage_root)
        except ValidationError:
            self._issue(
                severity="error",
                code="project_root_escape",
                resource_kind="project_root",
                record_id=project.id,
                managed_path=project.storage_root,
                message="The project storage root escapes the ReefVision data directory.",
            )
            return
        if not root.exists():
            self._issue(
                severity="error",
                code="project_root_missing",
                resource_kind="project_root",
                record_id=project.id,
                managed_path=project.storage_root,
                message="The project storage directory is missing.",
                repairable=True,
            )
        elif not root.is_dir():
            self._issue(
                severity="error",
                code="project_root_not_directory",
                resource_kind="project_root",
                record_id=project.id,
                managed_path=project.storage_root,
                message="The project storage root is not a directory.",
            )

    def _inspect_images(self, project_id: str) -> None:
        images = list(
            self.session.scalars(
                select(ImageAsset)
                .where(ImageAsset.project_id == project_id)
                .order_by(ImageAsset.created_at, ImageAsset.id)
            )
        )
        self.categories["image"].record_count = len(images)
        self.categories["thumbnail"].record_count = len(images)
        for image in images:
            self._inspect_file(
                resource_kind="image",
                record_id=image.id,
                managed_path=image.managed_path,
                expected_sha256=image.sha256,
            )
            if image.thumbnail_path:
                self._inspect_file(
                    resource_kind="thumbnail",
                    record_id=image.id,
                    managed_path=image.thumbnail_path,
                    missing_severity="warning",
                    repairable=True,
                )
            else:
                self._issue(
                    severity="warning",
                    code="thumbnail_reference_missing",
                    resource_kind="thumbnail",
                    record_id=image.id,
                    message="The image has no managed thumbnail reference.",
                    repairable=True,
                )

    def _inspect_masks(self, project_id: str) -> None:
        masks = list(
            self.session.scalars(
                select(MaskAnnotation)
                .join(ImageAsset, ImageAsset.id == MaskAnnotation.image_id)
                .where(
                    ImageAsset.project_id == project_id,
                    MaskAnnotation.deleted_at.is_(None),
                )
                .order_by(MaskAnnotation.created_at, MaskAnnotation.id)
            )
        )
        raster_masks = [mask for mask in masks if mask.mask_path]
        self.categories["raster_mask"].record_count = len(raster_masks)
        for mask in raster_masks:
            self._inspect_file(
                resource_kind="raster_mask",
                record_id=mask.id,
                managed_path=str(mask.mask_path),
            )
        for mask in masks:
            if mask.mask_path is None and not mask.polygon_json:
                self._issue(
                    severity="error",
                    code="mask_geometry_missing",
                    resource_kind="raster_mask",
                    record_id=mask.id,
                    message="The active mask has neither raster nor polygon geometry.",
                )

    def _inspect_models(self, project_id: str) -> None:
        models = list(
            self.session.scalars(
                select(ModelRegistration)
                .where(ModelRegistration.project_id == project_id)
                .order_by(ModelRegistration.created_at, ModelRegistration.id)
            )
        )
        self.categories["model"].record_count = len(models)
        for model in models:
            self._inspect_file(
                resource_kind="model",
                record_id=model.id,
                managed_path=model.managed_path,
                expected_sha256=model.sha256,
            )

    def _inspect_exports(self, project_id: str) -> None:
        exports = list(
            self.session.scalars(
                select(ExportRecord)
                .where(ExportRecord.project_id == project_id)
                .order_by(ExportRecord.created_at, ExportRecord.id)
            )
        )
        completed = [item for item in exports if item.status in {"completed", "succeeded"}]
        for kind in ("export_output", "export_manifest", "export_archive"):
            self.categories[kind].record_count = len(completed)
        for export in completed:
            self._inspect_directory(
                resource_kind="export_output",
                record_id=export.id,
                managed_path=export.output_path,
            )
            self._inspect_file(
                resource_kind="export_manifest",
                record_id=export.id,
                managed_path=export.manifest_path,
            )
            self._inspect_file(
                resource_kind="export_archive",
                record_id=export.id,
                managed_path=export.archive_path,
            )

    def _inspect_training(self, project_id: str) -> None:
        runs = list(
            self.session.scalars(
                select(TrainingRun)
                .where(TrainingRun.project_id == project_id)
                .order_by(TrainingRun.created_at, TrainingRun.id)
            )
        )
        self.categories["training_log"].record_count = len(runs)
        completed = [run for run in runs if run.status in {"completed", "succeeded"}]
        self.categories["training_checkpoint"].record_count = len(completed)
        for run in runs:
            if run.logs_path:
                self._inspect_path(
                    resource_kind="training_log",
                    record_id=run.id,
                    managed_path=run.logs_path,
                    expected_kind="either",
                    missing_severity="warning",
                )
            elif run.status in {"running", "completed", "succeeded", "failed"}:
                self._issue(
                    severity="warning",
                    code="training_log_reference_missing",
                    resource_kind="training_log",
                    record_id=run.id,
                    message="The training run has no persisted log path.",
                )
        for run in completed:
            if run.result_checkpoint_path:
                self._inspect_file(
                    resource_kind="training_checkpoint",
                    record_id=run.id,
                    managed_path=run.result_checkpoint_path,
                )
            else:
                self._issue(
                    severity="error",
                    code="completed_training_checkpoint_missing",
                    resource_kind="training_checkpoint",
                    record_id=run.id,
                    message="The completed training run has no checkpoint reference.",
                )

    def _inspect_videos(self, project_id: str) -> None:
        videos = list(
            self.session.scalars(
                select(VideoAsset)
                .where(VideoAsset.project_id == project_id)
                .order_by(VideoAsset.created_at, VideoAsset.id)
            )
        )
        self.categories["video"].record_count = len(videos)
        for video in videos:
            self._inspect_file(
                resource_kind="video",
                record_id=video.id,
                managed_path=video.managed_path,
                expected_sha256=video.sha256,
            )

    def _inspect_jobs(self, project_id: str, stale_job_minutes: int) -> None:
        jobs = list(
            self.session.scalars(
                select(Job).where(Job.project_id == project_id).order_by(Job.created_at, Job.id)
            )
        )
        self.categories["job"].record_count = len(jobs)
        cutoff = datetime.now(UTC) - timedelta(minutes=stale_job_minutes)
        for job in jobs:
            timestamp = job.started_at or job.created_at
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=UTC)
            if job.status in {"running", "cancel_requested"} and timestamp < cutoff:
                self._issue(
                    severity="warning",
                    code="stale_active_job",
                    resource_kind="job",
                    record_id=job.id,
                    message=(
                        f"The {job.job_type} job has remained {job.status!r} longer "
                        f"than {stale_job_minutes} minutes."
                    ),
                    repairable=True,
                )
            if job.status == "failed" and not job.error_message:
                self._issue(
                    severity="warning",
                    code="failed_job_without_error",
                    resource_kind="job",
                    record_id=job.id,
                    message="The failed job does not contain a persisted error message.",
                )

    def inspect(
        self,
        project_id: str,
        *,
        verify_checksums: bool,
        stale_job_minutes: int,
    ) -> ProjectIntegrityResponse:
        project = self._project(project_id)
        self.verify_checksums = verify_checksums
        self._inspect_project_root(project)
        self._inspect_images(project.id)
        self._inspect_masks(project.id)
        self._inspect_models(project.id)
        self._inspect_exports(project.id)
        self._inspect_training(project.id)
        self._inspect_videos(project.id)
        self._inspect_jobs(project.id, stale_job_minutes)

        categories = [self.categories[kind].response() for kind in CATEGORY_ORDER]
        error_count = sum(1 for issue in self.issues if issue.severity == "error")
        warning_count = sum(1 for issue in self.issues if issue.severity == "warning")
        referenced = sum(item.referenced_file_count for item in categories)
        existing = sum(item.existing_file_count for item in categories)
        missing = sum(item.missing_file_count for item in categories)
        total_bytes = sum(item.total_existing_bytes for item in categories)
        return ProjectIntegrityResponse(
            project_id=project.id,
            project_name=project.name,
            checked_at=datetime.now(UTC),
            verify_checksums=verify_checksums,
            stale_job_minutes=stale_job_minutes,
            valid=error_count == 0,
            error_count=error_count,
            warning_count=warning_count,
            total_referenced_files=referenced,
            existing_referenced_files=existing,
            missing_referenced_files=missing,
            total_existing_bytes=total_bytes,
            categories=categories,
            issues=sorted(
                self.issues,
                key=lambda item: (
                    {"error": 0, "warning": 1, "info": 2}[item.severity],
                    item.resource_kind,
                    item.record_id or "",
                    item.code,
                ),
            ),
        )
