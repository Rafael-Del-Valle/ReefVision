"""Project-managed storage, integrity, and safe-repair schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

IntegritySeverity = Literal["info", "warning", "error"]
IntegrityResourceKind = Literal[
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
]
ProjectRepairActionKind = Literal["create_project_root", "quarantine_orphan_file"]


class ProjectIntegrityIssue(BaseModel):
    severity: IntegritySeverity
    code: str
    resource_kind: IntegrityResourceKind
    record_id: str | None = None
    managed_path: str | None = None
    message: str
    repairable: bool = False


class ProjectIntegrityCategorySummary(BaseModel):
    resource_kind: IntegrityResourceKind
    record_count: int = Field(ge=0)
    referenced_file_count: int = Field(ge=0)
    existing_file_count: int = Field(ge=0)
    missing_file_count: int = Field(ge=0)
    total_existing_bytes: int = Field(ge=0)
    checksum_verified_count: int = Field(ge=0)
    checksum_mismatch_count: int = Field(ge=0)


class ProjectIntegrityResponse(BaseModel):
    project_id: str
    project_name: str
    checked_at: datetime
    verify_checksums: bool
    stale_job_minutes: int
    valid: bool
    error_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    total_referenced_files: int = Field(ge=0)
    existing_referenced_files: int = Field(ge=0)
    missing_referenced_files: int = Field(ge=0)
    total_existing_bytes: int = Field(ge=0)
    categories: list[ProjectIntegrityCategorySummary]
    issues: list[ProjectIntegrityIssue]


class ProjectRepairAction(BaseModel):
    action_id: str
    action_kind: ProjectRepairActionKind
    managed_path: str
    reason: str
    safe_automatic: bool = True
    size_bytes: int | None = Field(default=None, ge=0)
    modified_at: datetime | None = None


class ProjectRepairPlanResponse(BaseModel):
    project_id: str
    generated_at: datetime
    minimum_orphan_age_seconds: int = Field(ge=60)
    referenced_path_count: int = Field(ge=0)
    orphan_file_count: int = Field(ge=0)
    orphan_file_bytes: int = Field(ge=0)
    actions: list[ProjectRepairAction]
    warnings: list[str]


class ProjectRepairApplyRequest(BaseModel):
    action_ids: list[str] = Field(min_length=1, max_length=10000)
    minimum_orphan_age_seconds: int = Field(default=3600, ge=60, le=31_536_000)


class ProjectRepairApplyResponse(BaseModel):
    project_id: str
    applied_at: datetime
    applied_action_ids: list[str]
    skipped_action_ids: list[str]
    quarantined_paths: list[str]
    created_paths: list[str]
