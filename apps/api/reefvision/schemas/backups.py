"""Milestone 8 backup request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from reefvision.schemas.jobs import JobResponse

BackupVerificationStatus = Literal["valid", "valid_with_warnings", "invalid", "unsupported"]


class BackupCreateRequest(BaseModel):
    include_exports: bool = False
    include_logs: bool = False
    notes: str | None = Field(default=None, max_length=1000)


class BackupRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_id: str | None
    status: str
    format_version: str
    destination_path: str
    staging_path: str | None
    manifest_path: str
    completion_marker_path: str
    database_filename: str
    request_json: dict[str, Any]
    result_json: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class BackupCreateResponse(BaseModel):
    backup: BackupRecordResponse
    job: JobResponse


class BackupRestoreRequest(BaseModel):
    destination_name: str | None = Field(default=None, max_length=80)
    overwrite_existing: bool = False


class BackupRestoreResponse(BaseModel):
    backup_id: str
    destination_path: str
    verification_status: BackupVerificationStatus
    warnings: list[str]
    job: JobResponse


class BackupVerificationResponse(BaseModel):
    backup_id: str
    status: BackupVerificationStatus
    format_version: str | None
    application_version: str | None
    current_schema_revision: str | None
    completion_marker_present: bool
    manifest_path: str
    database_filename: str | None
    file_count: int
    total_size_bytes: int | None
    item_counts: dict[str, int]
    missing_files: list[str]
    checksum_failures: list[str]
    duplicate_entries: list[str]
    warnings: list[str]
    errors: list[str]
