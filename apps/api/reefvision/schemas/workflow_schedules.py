"""Public contracts for local schedules against saved workflow revisions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    model_validator,
)

SchedulePurpose = Literal["acquisition", "inference", "qc", "report"]
OccurrenceStatus = Literal[
    "queued",
    "running",
    "waiting_for_review",
    "cancel_requested",
    "cancelled",
    "succeeded",
    "failed",
]
ScheduleStatus = (
    Literal["scheduled", "paused", "waiting_previous_run", "blocked_storage", "dispatch_failed"]
    | OccurrenceStatus
)
ScheduleName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
ScheduleInterval = Annotated[int, Field(strict=True, ge=1, le=31_536_000)]
StorageBytes = Annotated[int, Field(strict=True, ge=0, le=2**63 - 1)]
Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


def _require_iso_datetime(value: object) -> object:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("Use an ISO 8601 time with a UTC offset") from exc
    if isinstance(value, datetime):
        return value
    raise ValueError("Use an ISO 8601 time with a UTC offset")


def _normalize_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


ScheduleTime = Annotated[
    AwareDatetime, BeforeValidator(_require_iso_datetime), AfterValidator(_normalize_utc)
]


class WorkflowScheduleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ScheduleName
    purpose: SchedulePurpose
    workflow_graph_record_id: UUID
    interval_seconds: ScheduleInterval
    next_due_at: ScheduleTime
    enabled: bool = True
    minimum_free_bytes: StorageBytes = 0
    inputs: dict[str, JsonValue] = Field(default_factory=dict)


class WorkflowScheduleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: Annotated[int, Field(strict=True, ge=1)]
    name: ScheduleName | None = None
    purpose: SchedulePurpose | None = None
    workflow_graph_record_id: UUID | None = None
    interval_seconds: ScheduleInterval | None = None
    next_due_at: ScheduleTime | None = None
    enabled: bool | None = None
    minimum_free_bytes: StorageBytes | None = None
    inputs: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def validate_changes(self) -> WorkflowScheduleUpdate:
        fields = self.model_fields_set - {"expected_revision"}
        if not fields or any(getattr(self, name) is None for name in fields):
            raise ValueError("Supply at least one non-null schedule change")
        return self


class WorkflowScheduleRead(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    purpose: SchedulePurpose
    workflow_graph_record_id: UUID
    graph_sha256: Digest
    inputs: dict[str, JsonValue]
    inputs_sha256: Digest
    interval_seconds: int
    next_due_at: AwareDatetime
    enabled: bool
    revision: int
    minimum_free_bytes: int
    last_status: ScheduleStatus
    last_message: str | None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class WorkflowScheduleOccurrenceRead(BaseModel):
    id: UUID
    project_id: UUID
    schedule_id: UUID
    scheduled_at: AwareDatetime
    created_at: AwareDatetime
    missed_intervals: int
    status: OccurrenceStatus
    detail: str | None
    workflow_run_id: UUID | None
    job_id: UUID | None
    graph_sha256: Digest
    inputs_sha256: Digest


class WorkflowSchedulePage(BaseModel):
    items: list[WorkflowScheduleRead]
    total: int


class WorkflowScheduleOccurrencePage(BaseModel):
    items: list[WorkflowScheduleOccurrenceRead]
    total: int
