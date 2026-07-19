"""Background job API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str | None
    parent_job_id: str | None = None
    job_type: str
    status: str
    priority: int = 100
    retry_count: int = 0
    max_retries: int = 0
    state_version: int = 0
    progress_current: int
    progress_total: int
    request_json: dict[str, Any]
    result_json: dict[str, Any] | None
    checkpoint_json: dict[str, Any] = Field(default_factory=dict)
    resource_requirements_json: dict[str, Any] = Field(default_factory=dict)
    resume_supported: bool = False
    worker_id: str | None = None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    heartbeat_at: datetime | None = None
    cancel_after: datetime | None = None
    paused_at: datetime | None = None
    last_transition_at: datetime | None = None
    completed_at: datetime | None


class JobDependencyCreateRequest(BaseModel):
    depends_on_job_id: str
    required_status: str = "succeeded"


class JobDependencyStatus(BaseModel):
    job_id: str
    required_status: str
    actual_status: str


class JobDependencyResponse(BaseModel):
    satisfied: bool
    dependencies: list[JobDependencyStatus]


class JobHeartbeatRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=120)
    progress_current: int | None = Field(default=None, ge=0)
    progress_total: int | None = Field(default=None, ge=0)
    checkpoint: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_progress(self) -> JobHeartbeatRequest:
        if (
            self.progress_current is not None
            and self.progress_total is not None
            and self.progress_total > 0
            and self.progress_current > self.progress_total
        ):
            raise ValueError("progress_current cannot exceed progress_total")
        return self


class JobRetryRequest(BaseModel):
    from_checkpoint: bool = True


class JobEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_id: str
    event_type: str
    from_status: str | None
    to_status: str | None
    actor: str
    message: str | None
    details_json: dict[str, Any]
    created_at: datetime
