"""System-information, compatibility, and migration schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from reefvision.schemas.jobs import JobResponse

SchemaStatus = Literal[
    "up_to_date",
    "migration_required",
    "uninitialized",
    "database_newer_than_code",
]


class SystemVersionResponse(BaseModel):
    application_version: str
    backup_format_version: str
    environment: str
    data_dir: str
    safe_mode: bool
    database_path: str | None
    current_schema_revision: str | None
    expected_schema_revision: str | None


class SystemCompatibilityResponse(BaseModel):
    application_version: str
    schema_status: SchemaStatus
    compatible_for_read_write: bool
    current_schema_revision: str | None
    expected_schema_revision: str | None
    pending_revisions: list[str]
    details: list[str]


class SystemMigrationStatusResponse(BaseModel):
    schema_status: SchemaStatus
    database_exists: bool
    current_schema_revision: str | None
    expected_schema_revision: str | None
    pending_revisions: list[str]


class SystemMigrationPreflightResponse(BaseModel):
    schema_status: SchemaStatus
    compatible_for_upgrade: bool
    requires_backup: bool
    database_exists: bool
    data_dir: str
    database_path: str | None
    current_schema_revision: str | None
    expected_schema_revision: str | None
    pending_revisions: list[str]
    disk_free_bytes: int | None
    warnings: list[str]
    blocking_issues: list[str]


class SystemLogFileResponse(BaseModel):
    name: str
    path: str
    size_bytes: int
    modified_at: datetime


class SystemLogsLocationResponse(BaseModel):
    logs_dir: str
    files: list[SystemLogFileResponse]


class SystemDiagnosticsCreateRequest(BaseModel):
    strict_redaction: bool = True
    notes: str | None = Field(default=None, max_length=1000)


class SystemDiagnosticsCreateResponse(BaseModel):
    job: JobResponse


class SystemDiagnosticsStatusResponse(BaseModel):
    job: JobResponse
    bundle_path: str | None
    bundle_size_bytes: int | None
    diagnostic_bundle_version: str | None


class SystemCommandShortcutStatusResponse(BaseModel):
    command_version: str
    command_directory: str
    support_directory: str
    repo_path: str | None
    path_contains_command_directory: bool
    start_command_exists: bool
    update_command_exists: bool
    support_start_exists: bool
    support_update_exists: bool
    start_command_managed: bool
    update_command_managed: bool
    verification_result: str
    notes: list[str]


class SystemCommandShortcutRepairResponse(BaseModel):
    status: SystemCommandShortcutStatusResponse
    output: str
