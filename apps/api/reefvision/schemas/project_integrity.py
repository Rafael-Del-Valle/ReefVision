"""Project-managed storage and record-integrity response schemas."""

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
