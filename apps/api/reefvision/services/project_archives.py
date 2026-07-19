"""Queue portable project archive and lifecycle operations."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import Job, Project
from reefvision.domain.errors import NotFoundError
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.project_archives import (
    ProjectArchiveExportRequest,
    ProjectArchiveImportRequest,
    ProjectArchiveQueueResponse,
    ProjectArchiveVerificationResponse,
    ProjectDuplicateRequest,
    ProjectRestoreResponse,
    ProjectStorageMigrationRequest,
)
from reefvision.schemas.projects import ProjectResponse
from reefvision.storage.project_archives import inspect_project_archive


class ProjectArchiveService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def _project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def queue_export(
        self,
        project_id: str,
        payload: ProjectArchiveExportRequest,
    ) -> ProjectArchiveQueueResponse:
        self._project(project_id)
        job = Job(
            project_id=project_id,
            job_type="project_archive_export",
            status="queued",
            progress_total=1,
            max_retries=1,
            resume_supported=False,
            request_json={
                "archive_id": str(uuid4()),
                **payload.model_dump(mode="json"),
            },
            result_json={"stage": "queued"},
            resource_requirements_json={"disk_intensive": True, "cpu_threads": 1},
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return ProjectArchiveQueueResponse(job=JobResponse.model_validate(job))

    def verify(self, archive_path: str) -> ProjectArchiveVerificationResponse:
        return inspect_project_archive(self.settings, archive_path)

    def queue_import(
        self,
        payload: ProjectArchiveImportRequest,
    ) -> ProjectArchiveQueueResponse:
        verification = self.verify(payload.archive_path)
        if not verification.valid:
            from reefvision.domain.errors import ValidationError

            raise ValidationError(
                "Project archive verification failed: " + "; ".join(verification.blockers)
            )
        job = Job(
            project_id=None,
            job_type="project_archive_import",
            status="queued",
            progress_total=1,
            max_retries=1,
            resume_supported=False,
            request_json=payload.model_dump(mode="json"),
            result_json={"stage": "queued", "verification": verification.model_dump(mode="json")},
            resource_requirements_json={"disk_intensive": True, "cpu_threads": 1},
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return ProjectArchiveQueueResponse(job=JobResponse.model_validate(job))

    def queue_duplicate(
        self,
        project_id: str,
        payload: ProjectDuplicateRequest,
    ) -> ProjectArchiveQueueResponse:
        self._project(project_id)
        job = Job(
            project_id=project_id,
            job_type="project_duplicate",
            status="queued",
            progress_total=2,
            max_retries=1,
            resume_supported=False,
            request_json=payload.model_dump(mode="json"),
            result_json={"stage": "queued"},
            resource_requirements_json={"disk_intensive": True, "cpu_threads": 1},
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return ProjectArchiveQueueResponse(job=JobResponse.model_validate(job))

    def queue_storage_migration(
        self,
        project_id: str,
        payload: ProjectStorageMigrationRequest,
    ) -> ProjectArchiveQueueResponse:
        self._project(project_id)
        job = Job(
            project_id=project_id,
            job_type="project_storage_migration",
            status="queued",
            progress_total=1,
            max_retries=0,
            resume_supported=False,
            request_json=payload.model_dump(mode="json"),
            result_json={"stage": "queued"},
            resource_requirements_json={"disk_intensive": True, "cpu_threads": 1},
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return ProjectArchiveQueueResponse(job=JobResponse.model_validate(job))

    def restore(self, project_id: str) -> ProjectRestoreResponse:
        project = self._project(project_id)
        project.archived_at = None
        project.updated_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(project)
        return ProjectRestoreResponse(project=ProjectResponse.model_validate(project))
