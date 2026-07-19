"""Portable complete-project archive and lifecycle schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.projects import ProjectResponse


class ProjectArchiveExportRequest(BaseModel):
    include_archived_records: bool = True
    notes: str | None = Field(default=None, max_length=5000)


class ProjectArchiveImportRequest(BaseModel):
    archive_path: str = Field(min_length=1, max_length=4000)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(default=None, min_length=1, max_length=220)
    restore_as_active: bool = True


class ProjectDuplicateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(default=None, min_length=1, max_length=220)
    include_archived_records: bool = True


class ProjectStorageMigrationRequest(BaseModel):
    destination_relative_path: str = Field(min_length=1, max_length=500)
    mode: Literal["move", "copy"] = "move"


class ProjectArchiveQueueResponse(BaseModel):
    job: JobResponse


class ProjectArchiveVerificationResponse(BaseModel):
    archive_path: str
    valid: bool
    format_version: str | None
    application_version: str | None
    source_schema_revision: str | None
    source_project_id: str | None
    source_project_name: str | None
    table_count: int
    record_count: int
    file_count: int
    total_file_bytes: int
    missing_tables: list[str]
    incompatible_columns: list[str]
    checksum_failures: list[str]
    warnings: list[str]
    blockers: list[str]


class ProjectRestoreResponse(BaseModel):
    project: ProjectResponse
