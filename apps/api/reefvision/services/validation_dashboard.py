"""Unified project validation dashboard across database, files, ML, and workflows."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from reefvision import __version__
from reefvision.config import Settings
from reefvision.db.models import (
    Annotation,
    DatasetVersion,
    ExportRecord,
    ImageAsset,
    Job,
    LabelClass,
    MaskAnnotation,
    ModelRegistration,
    Project,
    TrainingRun,
    VideoAsset,
    Workflow,
    WorkflowRun,
)
from reefvision.domain.errors import NotFoundError
from reefvision.schemas.validation_dashboard import (
    CheckStatus,
    ValidationDashboardCheck,
    ValidationDashboardResponse,
)
from reefvision.services.project_integrity import ProjectIntegrityService
from reefvision.services.recovery import RecoveryService
from reefvision.storage.projects import resolve_managed_project_path


class ValidationDashboardService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def build(
        self,
        project_id: str,
        *,
        verify_checksums: bool = False,
        stale_job_minutes: int = 15,
    ) -> ValidationDashboardResponse:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        checks = [
            self._database_check(),
            self._managed_files_check(
                project,
                verify_checksums=verify_checksums,
                stale_job_minutes=stale_job_minutes,
            ),
            self._models_check(project.id),
            self._datasets_check(project.id),
            self._annotations_check(project.id),
            self._class_maps_check(project.id),
            self._training_check(project.id),
            self._videos_check(project.id),
            self._exports_check(project.id),
            self._workflows_check(project.id),
            self._disk_check(project),
            self._version_check(),
            self._recovery_check(project.id, stale_job_minutes),
        ]
        rank: dict[CheckStatus, int] = {"pass": 0, "warning": 1, "error": 2}
        overall = max((check.status for check in checks), key=rank.__getitem__)
        disk = shutil.disk_usage(self.settings.resolved_data_dir)
        return ValidationDashboardResponse(
            project_id=project.id,
            project_name=project.name,
            generated_at=datetime.now(UTC),
            reefvision_version=__version__,
            overall_status=overall,
            checks=checks,
            error_count=sum(check.status == "error" for check in checks),
            warning_count=sum(check.status == "warning" for check in checks),
            disk_total_bytes=disk.total,
            disk_free_bytes=disk.free,
        )

    def _database_check(self) -> ValidationDashboardCheck:
        details: dict[str, Any] = {}
        status: CheckStatus = "pass"
        recommendation = None
        try:
            foreign_keys = int(self.session.execute(text("PRAGMA foreign_keys")).scalar_one())
            details["sqlite_foreign_keys"] = bool(foreign_keys)
            if not foreign_keys:
                status = "error"
                recommendation = "Enable SQLite foreign-key enforcement before editing projects."
        except SQLAlchemyError as exc:
            status = "warning"
            details["foreign_key_probe_error"] = str(exc)
            recommendation = "Run the database diagnostics command in a SQLite-backed checkout."
        try:
            details["table_count"] = int(
                self.session.execute(
                    text("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
                ).scalar_one()
            )
            integrity = str(self.session.execute(text("PRAGMA quick_check")).scalar_one())
            details["quick_check"] = integrity
            if integrity.casefold() != "ok":
                status = "error"
                recommendation = "Restore a verified backup before continuing writes."
        except SQLAlchemyError as exc:
            status = "error"
            details["quick_check_error"] = str(exc)
            recommendation = "Run SQLite recovery diagnostics and verify the most recent backup."
        return ValidationDashboardCheck(
            category="database",
            status=status,
            code="database_integrity",
            summary="Database schema and SQLite integrity checks completed.",
            details=details,
            recommendation=recommendation,
        )

    def _managed_files_check(
        self,
        project: Project,
        *,
        verify_checksums: bool,
        stale_job_minutes: int,
    ) -> ValidationDashboardCheck:
        report = ProjectIntegrityService(self.session, self.settings).inspect(
            project.id,
            verify_checksums=verify_checksums,
            stale_job_minutes=stale_job_minutes,
        )
        status: CheckStatus = (
            "error" if report.error_count else "warning" if report.warning_count else "pass"
        )
        return ValidationDashboardCheck(
            category="managed_files",
            status=status,
            code="managed_file_integrity",
            summary=(
                f"{report.existing_referenced_files} of {report.total_referenced_files} "
                "referenced paths are available."
            ),
            details={
                "errors": report.error_count,
                "warnings": report.warning_count,
                "missing": report.missing_referenced_files,
                "bytes": report.total_existing_bytes,
                "checksums_verified": sum(
                    item.checksum_verified_count for item in report.categories
                ),
                "checksum_mismatches": sum(
                    item.checksum_mismatch_count for item in report.categories
                ),
            },
            recommendation=(
                "Open the Integrity workspace and resolve missing or mismatched files."
                if status != "pass"
                else None
            ),
        )

    def _models_check(self, project_id: str) -> ValidationDashboardCheck:
        models = list(
            self.session.scalars(
                select(ModelRegistration).where(ModelRegistration.project_id == project_id)
            )
        )
        missing = []
        checksum_fields = 0
        for model in models:
            if model.sha256:
                checksum_fields += 1
            try:
                exists = resolve_managed_project_path(
                    self.settings,
                    model.managed_path,
                ).is_file()
            except Exception:
                exists = False
            if not exists:
                missing.append(model.id)
        status: CheckStatus = "error" if missing else "pass"
        return ValidationDashboardCheck(
            category="models",
            status=status,
            code="model_registry_integrity",
            summary=f"{len(models)} registered models inspected.",
            details={
                "registered": len(models),
                "missing_files": missing,
                "checksummed": checksum_fields,
                "tasks": sorted({model.task for model in models}),
            },
            recommendation=(
                "Reinstall or remove model registrations whose managed files are missing."
                if missing
                else None
            ),
        )

    def _datasets_check(self, project_id: str) -> ValidationDashboardCheck:
        versions = list(
            self.session.scalars(
                select(DatasetVersion).where(DatasetVersion.project_id == project_id)
            )
        )
        incomplete = [version.id for version in versions if version.status != "complete"]
        malformed = [
            version.id
            for version in versions
            if version.status == "complete"
            and (not version.manifest_sha256 or not version.manifest_json)
        ]
        status: CheckStatus = "error" if malformed else "warning" if incomplete else "pass"
        return ValidationDashboardCheck(
            category="datasets",
            status=status,
            code="immutable_dataset_versions",
            summary=f"{len(versions)} immutable dataset versions inspected.",
            details={
                "complete": sum(version.status == "complete" for version in versions),
                "incomplete_ids": incomplete,
                "malformed_ids": malformed,
                "images": sum(version.image_count for version in versions),
                "annotations": sum(version.annotation_count for version in versions),
                "masks": sum(version.mask_annotation_count for version in versions),
            },
            recommendation=(
                "Regenerate incomplete or malformed immutable dataset versions."
                if status != "pass"
                else None
            ),
        )

    def _annotations_check(self, project_id: str) -> ValidationDashboardCheck:
        box_count = int(
            self.session.scalar(
                select(func.count(Annotation.id))
                .join(ImageAsset, ImageAsset.id == Annotation.image_id)
                .where(ImageAsset.project_id == project_id, Annotation.deleted_at.is_(None))
            )
            or 0
        )
        masks = list(
            self.session.scalars(
                select(MaskAnnotation)
                .join(ImageAsset, ImageAsset.id == MaskAnnotation.image_id)
                .where(
                    ImageAsset.project_id == project_id,
                    MaskAnnotation.deleted_at.is_(None),
                )
            )
        )
        invalid = [
            mask.id
            for mask in masks
            if not mask.mask_path and not mask.polygon_json
        ]
        status: CheckStatus = "error" if invalid else "pass"
        return ValidationDashboardCheck(
            category="annotations",
            status=status,
            code="annotation_geometry",
            summary=f"{box_count} boxes and {len(masks)} active masks inspected.",
            details={"boxes": box_count, "masks": len(masks), "invalid_mask_ids": invalid},
            recommendation=(
                "Repair or remove active mask records with no geometry." if invalid else None
            ),
        )

    def _class_maps_check(self, project_id: str) -> ValidationDashboardCheck:
        classes = list(
            self.session.scalars(
                select(LabelClass)
                .where(LabelClass.project_id == project_id)
                .order_by(LabelClass.class_index)
            )
        )
        duplicate_indexes = sorted(
            index
            for index in {item.class_index for item in classes}
            if sum(other.class_index == index for other in classes) > 1
        )
        active_names = {item.name for item in classes if item.is_active}
        unknown_model_classes: dict[str, list[str]] = {}
        for model in self.session.scalars(
            select(ModelRegistration).where(ModelRegistration.project_id == project_id)
        ):
            raw = model.class_map_json
            names = {
                str(value)
                for value in (raw.values() if isinstance(raw, dict) else [])
            }
            unknown = sorted(names - active_names)
            if unknown:
                unknown_model_classes[model.id] = unknown
        status: CheckStatus = (
            "error" if duplicate_indexes else "warning" if unknown_model_classes else "pass"
        )
        return ValidationDashboardCheck(
            category="class_maps",
            status=status,
            code="class_map_compatibility",
            summary=f"{len(classes)} project classes compared with registered models.",
            details={
                "active_classes": sorted(active_names),
                "duplicate_indexes": duplicate_indexes,
                "unknown_model_classes": unknown_model_classes,
            },
            recommendation=(
                "Use the class-mapping workflow before inference or export."
                if status != "pass"
                else None
            ),
        )

    def _training_check(self, project_id: str) -> ValidationDashboardCheck:
        runs = list(
            self.session.scalars(
                select(TrainingRun).where(TrainingRun.project_id == project_id)
            )
        )
        failed = [run.id for run in runs if run.status == "failed"]
        completed_without_checkpoint = [
            run.id
            for run in runs
            if run.status in {"completed", "succeeded"} and not run.result_checkpoint_path
        ]
        status: CheckStatus = (
            "error"
            if completed_without_checkpoint
            else "warning"
            if failed
            else "pass"
        )
        return ValidationDashboardCheck(
            category="training",
            status=status,
            code="training_artifacts",
            summary=f"{len(runs)} training runs inspected.",
            details={
                "failed_ids": failed,
                "completed_without_checkpoint": completed_without_checkpoint,
                "running": sum(run.status == "running" for run in runs),
            },
            recommendation=(
                "Review failed runs and regenerate missing final checkpoints."
                if status != "pass"
                else None
            ),
        )

    def _videos_check(self, project_id: str) -> ValidationDashboardCheck:
        videos = list(
            self.session.scalars(
                select(VideoAsset).where(VideoAsset.project_id == project_id)
            )
        )
        missing = []
        for video in videos:
            try:
                if not resolve_managed_project_path(
                    self.settings,
                    video.managed_path,
                ).is_file():
                    missing.append(video.id)
            except Exception:
                missing.append(video.id)
        return ValidationDashboardCheck(
            category="videos",
            status="error" if missing else "pass",
            code="video_integrity",
            summary=f"{len(videos)} managed videos inspected.",
            details={"missing_ids": missing},
            recommendation="Restore missing managed video files." if missing else None,
        )

    def _exports_check(self, project_id: str) -> ValidationDashboardCheck:
        exports = list(
            self.session.scalars(
                select(ExportRecord).where(ExportRecord.project_id == project_id)
            )
        )
        failed = [item.id for item in exports if item.status == "failed"]
        queued = [item.id for item in exports if item.status in {"queued", "running"}]
        status: CheckStatus = "warning" if failed or queued else "pass"
        return ValidationDashboardCheck(
            category="exports",
            status=status,
            code="export_status",
            summary=f"{len(exports)} export records inspected.",
            details={"failed_ids": failed, "active_ids": queued},
            recommendation="Retry failed exports after resolving integrity issues." if failed else None,
        )

    def _workflows_check(self, project_id: str) -> ValidationDashboardCheck:
        workflows = list(
            self.session.scalars(select(Workflow).where(Workflow.project_id == project_id))
        )
        runs = list(
            self.session.scalars(select(WorkflowRun).where(WorkflowRun.project_id == project_id))
        )
        failed = [run.id for run in runs if run.status == "failed"]
        status: CheckStatus = "warning" if failed else "pass"
        return ValidationDashboardCheck(
            category="workflows",
            status=status,
            code="workflow_integrity",
            summary=f"{len(workflows)} workflows and {len(runs)} runs inspected.",
            details={
                "drafts": sum(item.status == "draft" for item in workflows),
                "published": sum(item.status == "published" for item in workflows),
                "failed_run_ids": failed,
            },
            recommendation="Inspect failed workflow node state and retry from checkpoint." if failed else None,
        )

    def _disk_check(self, project: Project) -> ValidationDashboardCheck:
        disk = shutil.disk_usage(self.settings.resolved_data_dir)
        ratio = disk.free / max(disk.total, 1)
        try:
            project_root = resolve_managed_project_path(self.settings, project.storage_root)
            project_bytes = sum(
                path.stat().st_size for path in project_root.rglob("*") if path.is_file()
            ) if project_root.is_dir() else 0
        except Exception:
            project_bytes = 0
        status: CheckStatus = "error" if ratio < 0.02 else "warning" if ratio < 0.10 else "pass"
        return ValidationDashboardCheck(
            category="disk",
            status=status,
            code="disk_capacity",
            summary=f"{ratio:.1%} of the data volume is free.",
            details={
                "total_bytes": disk.total,
                "used_bytes": disk.used,
                "free_bytes": disk.free,
                "project_bytes": project_bytes,
            },
            recommendation=(
                "Free disk space or migrate the project storage root before starting large jobs."
                if status != "pass"
                else None
            ),
        )

    def _version_check(self) -> ValidationDashboardCheck:
        api_root = Path(__file__).resolve().parents[2]
        config = Config()
        config.set_main_option("script_location", str(api_root / "migrations"))
        expected_heads = ScriptDirectory.from_config(config).get_heads()
        current: list[str] = []
        try:
            rows = self.session.execute(text("SELECT version_num FROM alembic_version"))
            current = [str(row[0]) for row in rows]
        except SQLAlchemyError:
            pass
        status: CheckStatus = "pass" if current == expected_heads else "warning"
        return ValidationDashboardCheck(
            category="versions",
            status=status,
            code="version_compatibility",
            summary="ReefVision and database migration versions inspected.",
            details={
                "reefvision_version": __version__,
                "database_revisions": current,
                "expected_heads": expected_heads,
            },
            recommendation=(
                "Run Alembic upgrade head before opening the project in the packaged app."
                if status != "pass"
                else None
            ),
        )

    def _recovery_check(
        self,
        project_id: str,
        stale_job_minutes: int,
    ) -> ValidationDashboardCheck:
        plan = RecoveryService(self.session, self.settings).plan(
            project_id,
            stale_after_seconds=max(stale_job_minutes * 60, 30),
        )
        manual = [item.issue_id for item in plan.issues if not item.safe_automatic]
        status: CheckStatus = (
            "error" if manual else "warning" if plan.issues else "pass"
        )
        return ValidationDashboardCheck(
            category="recovery",
            status=status,
            code="restart_recovery_plan",
            summary=f"{len(plan.issues)} restart or incomplete-artifact issues detected.",
            details={
                "automatic_issue_ids": plan.automatic_issue_ids,
                "manual_issue_ids": manual,
            },
            recommendation=(
                "Review the project restart plan before continuing long-running jobs."
                if plan.issues
                else None
            ),
        )
