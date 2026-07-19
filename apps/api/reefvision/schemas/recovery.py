"""Crash-recovery inspection and safe-action schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

RecoveryCategory = Literal[
    "stale_job",
    "interrupted_workflow",
    "temporary_file",
    "missing_mask",
    "missing_model",
    "incomplete_export",
]
RecoveryAction = Literal[
    "requeue_from_checkpoint",
    "mark_failed",
    "complete_cancellation",
    "quarantine",
    "manual_repair",
]


class RecoveryIssue(BaseModel):
    issue_id: str
    category: RecoveryCategory
    record_id: str | None = None
    managed_path: str | None = None
    message: str
    recommended_action: RecoveryAction
    safe_automatic: bool
    detected_at: datetime
    details: dict[str, object] = Field(default_factory=dict)


class RecoveryPlanResponse(BaseModel):
    project_id: str
    generated_at: datetime
    stale_after_seconds: int
    issues: list[RecoveryIssue]
    automatic_issue_ids: list[str]


class RecoveryApplyRequest(BaseModel):
    issue_ids: list[str] = Field(min_length=1, max_length=500)


class RecoveryApplyResponse(BaseModel):
    project_id: str
    applied_at: datetime
    applied_issue_ids: list[str]
    skipped_issue_ids: list[str]
    quarantined_paths: list[str]
