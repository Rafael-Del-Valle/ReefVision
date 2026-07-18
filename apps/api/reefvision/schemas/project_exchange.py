"""Versioned ReefVision project exchange schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProjectExchangeCreateRequest(BaseModel):
    include_media: bool = False
    include_model_weights: bool = False
    include_generated_artifacts: bool = False
    notes: str | None = Field(default=None, max_length=2000)


class ProjectExchangePackageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    job_id: str | None
    direction: str
    status: str
    format_version: str
    manifest_json: dict[str, Any]
    manifest_sha256: str
    archive_path: str
    options_json: dict[str, Any]
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


class ProjectExchangeCreateResponse(BaseModel):
    package: ProjectExchangePackageResponse
    job_id: str


class ProjectExchangeInspectionResponse(BaseModel):
    compatible: bool
    format_name: str | None
    format_version: str | None
    application_version: str | None
    manifest_sha256: str | None
    project_name: str | None
    section_counts: dict[str, int]
    included_media_count: int
    warnings: list[str]
    errors: list[str]
