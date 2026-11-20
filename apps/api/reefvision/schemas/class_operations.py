"""Schemas for reassignment, reassign-delete, and operation audit records."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ClassOperationType = Literal["reassign", "reassign_delete"]
ClassOperationStatus = Literal[
    "previewed",
    "queued",
    "running",
    "completed",
    "failed",
    "rolled_back",
    "cancelled",
]


class ClassOperationClassSnapshotResponse(BaseModel):
    id: str
    name: str
    class_index: int
    display_order: int
    display_color: str
    scientific_name: str | None = None
    state_name: str | None = None
    description: str | None = None
    archived_at: datetime | None = None


class ClassOperationRecordGroupResponse(BaseModel):
    key: str
    label: str
    count: int = Field(ge=0)
    record_ids: list[str] = Field(default_factory=list)


class ClassOperationCompatibilityImpactResponse(BaseModel):
    key: str
    label: str
    status: str
    message: str
    record_ids: list[str] = Field(default_factory=list)


class ClassOperationPlanResponse(BaseModel):
    mutable_records: list[ClassOperationRecordGroupResponse]
    protected_records: list[ClassOperationRecordGroupResponse]
    blocking_records: list[ClassOperationRecordGroupResponse]
    compatibility_impacts: list[ClassOperationCompatibilityImpactResponse]
    warnings: list[str]
    blockers: list[str]


class ClassOperationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    source_class_id: str
    target_class_id: str | None
    operation_type: ClassOperationType
    status: ClassOperationStatus
    preview_checksum: str
    requested_by_identity: str
    source_class: ClassOperationClassSnapshotResponse
    target_class: ClassOperationClassSnapshotResponse | None
    plan: ClassOperationPlanResponse
    affected_counts: list[ClassOperationRecordGroupResponse]
    protected_reference_counts: list[ClassOperationRecordGroupResponse]
    warnings: list[str]
    failures: list[str]
    rollback_result: dict[str, object]
    final_state: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    @field_validator("created_at", "updated_at", "started_at", "completed_at")
    @classmethod
    def restore_timestamp_timezone(cls, value: datetime | None) -> datetime | None:
        # SQLite reads UTC values without a timezone. Return the same audit
        # timestamps both immediately after commit and on an idempotent retry.
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class ClassOperationPreviewRequest(BaseModel):
    target_class_id: str = Field(min_length=1, max_length=36)
    notes: str | None = Field(default=None, max_length=5000)


class ClassOperationExecuteRequest(BaseModel):
    operation_id: str = Field(min_length=1, max_length=36)
    preview_checksum: str = Field(min_length=64, max_length=64)
    notes: str | None = Field(default=None, max_length=5000)
