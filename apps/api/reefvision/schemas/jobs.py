"""Background job API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str | None
    job_type: str
    status: str
    progress_current: int
    progress_total: int
    request_json: dict[str, Any]
    result_json: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class ComputeLimitsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cpu_slots: int = Field(ge=0, le=8, strict=True)
    gpu_slots: int = Field(ge=0, le=1, strict=True)


class ComputeResources(ComputeLimitsRequest):
    cpu_in_use: int
    gpu_in_use: int


class ComputeJob(BaseModel):
    job: JobResponse
    pool: Literal["cpu", "gpu"]
    admission: Literal["ready", "waiting", "reserved", "inactive"]
    reason: str | None = None
    heartbeat_at: datetime | None = None
    checkpoint_available: bool = False
    can_retry: bool
    can_cancel: bool


class ComputeJobPage(BaseModel):
    items: list[ComputeJob]
    total: int
