"""Crash/restart inspection and conservative automatic recovery actions."""

from __future__ import annotations

import hashlib
import shutil
from datetime import UTC, datetime, timedelta
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
    WorkflowRun,
)
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.recovery import (
    RecoveryAction,
    RecoveryApplyResponse,
    RecoveryIssue,
    RecoveryPlanResponse,
)
from reefvision.services.job_orchestration import JobOrchestrationService
from reefvision.storage.projects import resolve_managed_project_path

_ACTIVE = {"running", "pause_requested", "cancel_requested"}
_TERMINAL = {"succeeded", "failed", "cancelled"}


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _issue_id(category: str, record_id: str | None, path: str | None) -> str:
    value = f"{category}|{record_id or ''}|{path or ''}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()[:24]


class RecoveryService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.jobs = JobOrchestrationService(session)

    def plan(
        self,
        project_id: str,
        *,
        stale_after_seconds: int = 300,
    ) -> RecoveryPlanResponse:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        if stale_after_seconds < 30:
            raise ValidationError("stale_after_seconds must be at least 30")
        now = datetime.now(UTC)
        cutoff = now - timedelta(seconds=stale_after_seconds)
        issues: list[RecoveryIssue] = []
        issues.extend(self._job_issues(project.id, cutoff, now))
        issues.extend(self._workflow_issues(project.id, now))
        issues.extend(self._missing_annotation_issues(project.id, now))
        issues.extend(self._missing_model_issues(project.id, now))
        issues.extend(self._export_issues(project.id, now))
        issues.extend(self._temporary_file_issues(project, cutoff, now))
        issues.sort(
            key=lambda item: (
                item.category,
                item.record_id or "",
                item.managed_path or "",
            )
        )
        return RecoveryPlanResponse(
            project_id=project.id,
            generated_at=now,
            stale_after_seconds=stale_after_seconds,
            issues=issues,
            automatic_issue_ids=[item.issue_id for item in issues if item.safe_automatic],
        )

    def apply(
        self,
        project_id: str,
        issue_ids: list[str],
        *,
        stale_after_seconds: int = 300,
    ) -> RecoveryApplyResponse:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        plan = self.plan(project_id, stale_after_seconds=stale_after_seconds)
        requested = set(issue_ids)
        known = {issue.issue_id: issue for issue in plan.issues}
        if requested - known.keys():
            raise ValidationError("Recovery plan changed; regenerate it before applying actions")
        applied: list[str] = []
        skipped: list[str] = []
        quarantined: list[str] = []
        for issue_id in issue_ids:
            issue = known[issue_id]
            if not issue.safe_automatic:
                skipped.append(issue_id)
                continue
            if issue.category == "temporary_file" and issue.managed_path:
                quarantined.append(self._quarantine(project, issue.managed_path))
                applied.append(issue_id)
            elif issue.category == "stale_job" and issue.record_id:
                self._recover_job(issue.record_id)
                applied.append(issue_id)
            elif issue.category == "interrupted_workflow" and issue.record_id:
                self._recover_workflow(issue.record_id)
                applied.append(issue_id)
            else:
                skipped.append(issue_id)
        self.session.commit()
        return RecoveryApplyResponse(
            project_id=project.id,
            applied_at=datetime.now(UTC),
            applied_issue_ids=applied,
            skipped_issue_ids=skipped,
            quarantined_paths=quarantined,
        )

    def _job_issues(
        self,
        project_id: str,
        cutoff: datetime,
        now: datetime,
    ) -> list[RecoveryIssue]:
        issues: list[RecoveryIssue] = []
        for job in self.session.scalars(
            select(Job).where(Job.project_id == project_id, Job.status.in_(_ACTIVE))
        ):
            heartbeat = _utc(job.heartbeat_at) or _utc(job.started_at) or _utc(job.created_at)
            if heartbeat is not None and heartbeat >= cutoff:
                continue
            action: RecoveryAction
            if job.status == "cancel_requested":
                action = "complete_cancellation"
            elif job.resume_supported:
                action = "requeue_from_checkpoint"
            else:
                action = "mark_failed"
            issues.append(
                RecoveryIssue(
                    issue_id=_issue_id("stale_job", job.id, None),
                    category="stale_job",
                    record_id=job.id,
                    message=f"{job.job_type} job has no current worker heartbeat",
                    recommended_action=action,
                    safe_automatic=True,
                    detected_at=now,
                    details={
                        "status": job.status,
                        "resume_supported": job.resume_supported,
                        "retry_count": job.retry_count,
                        "max_retries": job.max_retries,
                    },
                )
            )
        return issues

    def _workflow_issues(self, project_id: str, now: datetime) -> list[RecoveryIssue]:
        issues: list[RecoveryIssue] = []
        runs = self.session.scalars(
            select(WorkflowRun).where(
                WorkflowRun.project_id == project_id,
                WorkflowRun.status.in_(("running", "cancel_requested")),
            )
        )
        for run in runs:
            job = self.session.get(Job, run.job_id) if run.job_id else None
            if job is not None and job.status not in _TERMINAL:
                continue
            issues.append(
                RecoveryIssue(
                    issue_id=_issue_id("interrupted_workflow", run.id, None),
                    category="interrupted_workflow",
                    record_id=run.id,
                    message="Workflow run is active but its parent job is missing or terminal",
                    recommended_action="mark_failed",
                    safe_automatic=True,
                    detected_at=now,
                    details={
                        "workflow_id": run.workflow_id,
                        "job_status": job.status if job else None,
                    },
                )
            )
        return issues

    def _missing_annotation_issues(
        self,
        project_id: str,
        now: datetime,
    ) -> list[RecoveryIssue]:
        issues: list[RecoveryIssue] = []
        masks = self.session.scalars(
            select(MaskAnnotation)
            .join(ImageAsset, ImageAsset.id == MaskAnnotation.image_id)
            .where(ImageAsset.project_id == project_id)
        )
        for mask in masks:
            if mask.geometry_kind != "raster_mask" or not mask.mask_path:
                continue
            try:
                path = resolve_managed_project_path(self.settings, mask.mask_path)
            except ValidationError:
                path = Path("__unsafe__")
            if path.is_file():
                continue
            issues.append(
                RecoveryIssue(
                    issue_id=_issue_id("missing_mask", mask.id, mask.mask_path),
                    category="missing_mask",
                    record_id=mask.id,
                    managed_path=mask.mask_path,
                    message="Raster-mask database revision has no readable managed file",
                    recommended_action="manual_repair",
                    safe_automatic=False,
                    detected_at=now,
                )
            )
        return issues

    def _missing_model_issues(self, project_id: str, now: datetime) -> list[RecoveryIssue]:
        issues: list[RecoveryIssue] = []
        for model in self.session.scalars(
            select(ModelRegistration).where(ModelRegistration.project_id == project_id)
        ):
            try:
                path = resolve_managed_project_path(self.settings, model.managed_path)
            except ValidationError:
                path = Path("__unsafe__")
            if path.is_file():
                continue
            issues.append(
                RecoveryIssue(
                    issue_id=_issue_id("missing_model", model.id, model.managed_path),
                    category="missing_model",
                    record_id=model.id,
                    managed_path=model.managed_path,
                    message="Registered model metadata points to missing managed content",
                    recommended_action="manual_repair",
                    safe_automatic=False,
                    detected_at=now,
                )
            )
        return issues

    def _export_issues(self, project_id: str, now: datetime) -> list[RecoveryIssue]:
        issues: list[RecoveryIssue] = []
        for export in self.session.scalars(
            select(ExportRecord).where(ExportRecord.project_id == project_id)
        ):
            missing: list[str] = []
            for managed_path in (
                export.output_path,
                export.manifest_path,
                export.archive_path,
            ):
                try:
                    exists = resolve_managed_project_path(
                        self.settings,
                        managed_path,
                    ).exists()
                except ValidationError:
                    exists = False
                if not exists:
                    missing.append(managed_path)
            if export.status != "succeeded" or not missing:
                continue
            issues.append(
                RecoveryIssue(
                    issue_id=_issue_id("incomplete_export", export.id, missing[0]),
                    category="incomplete_export",
                    record_id=export.id,
                    managed_path=missing[0],
                    message="Succeeded export is missing one or more declared artifacts",
                    recommended_action="manual_repair",
                    safe_automatic=False,
                    detected_at=now,
                    details={"missing_paths": missing},
                )
            )
        return issues

    def _temporary_file_issues(
        self,
        project: Project,
        cutoff: datetime,
        now: datetime,
    ) -> list[RecoveryIssue]:
        project_root = resolve_managed_project_path(self.settings, project.storage_root)
        if not project_root.is_dir():
            return []
        issues: list[RecoveryIssue] = []
        for path in project_root.rglob("*"):
            if not path.is_file() or ".quarantine" in path.parts:
                continue
            if not (
                path.name.startswith(".rv-")
                or path.suffix.casefold() in {".tmp", ".part"}
            ):
                continue
            modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
            if modified >= cutoff:
                continue
            managed = path.relative_to(self.settings.resolved_data_dir).as_posix()
            issues.append(
                RecoveryIssue(
                    issue_id=_issue_id("temporary_file", None, managed),
                    category="temporary_file",
                    managed_path=managed,
                    message="Old unpublished temporary artifact remains after interruption",
                    recommended_action="quarantine",
                    safe_automatic=True,
                    detected_at=now,
                    details={
                        "size_bytes": path.stat().st_size,
                        "modified_at": modified.isoformat(),
                    },
                )
            )
        return issues

    def _recover_job(self, job_id: str) -> None:
        job = self.jobs.get(job_id)
        if job.status == "cancel_requested":
            self.jobs.transition(
                job.id,
                "cancelled",
                actor="recovery",
                event_type="recovery_completed_cancellation",
                commit=False,
            )
            return
        self.jobs.transition(
            job.id,
            "failed",
            actor="recovery",
            event_type="recovery_worker_lost",
            message="Recovered after interrupted worker execution",
            commit=False,
        )
        if job.resume_supported:
            job.max_retries = max(job.max_retries, job.retry_count + 1)
            self.jobs.retry(job.id, from_checkpoint=True)

    def _recover_workflow(self, run_id: str) -> None:
        run = self.session.get(WorkflowRun, run_id)
        if run is None:
            raise NotFoundError("Workflow run not found")
        run.status = "failed"
        run.stage = "recovered_interruption"
        run.error_message = "Recovered inconsistent workflow state after restart"
        run.completed_at = datetime.now(UTC)

    def _quarantine(self, project: Project, managed_path: str) -> str:
        source = resolve_managed_project_path(self.settings, managed_path)
        if not source.is_file():
            raise ValidationError("Temporary file disappeared before quarantine")
        project_root = resolve_managed_project_path(self.settings, project.storage_root)
        relative = source.relative_to(project_root)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        destination = project_root / ".quarantine" / stamp / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), destination)
        return destination.relative_to(self.settings.resolved_data_dir).as_posix()
