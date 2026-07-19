"""Project validation dashboard response models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

CheckStatus = Literal["pass", "warning", "error"]


class ValidationDashboardCheck(BaseModel):
    category: str
    status: CheckStatus
    code: str
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)
    recommendation: str | None = None


class ValidationDashboardResponse(BaseModel):
    project_id: str
    project_name: str
    generated_at: datetime
    reefvision_version: str
    overall_status: CheckStatus
    checks: list[ValidationDashboardCheck]
    error_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    disk_total_bytes: int = Field(ge=0)
    disk_free_bytes: int = Field(ge=0)
