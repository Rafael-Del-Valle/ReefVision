"""Previewed, conservative workflow artifact cleanup contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

WorkflowCleanupActionKind = Literal["quarantine_file", "clear_missing_reference"]


class WorkflowArtifactCleanupPreviewRequest(BaseModel):
    node_ids: list[str] = Field(default_factory=list, max_length=1000)


class WorkflowArtifactCleanupAction(BaseModel):
    action_id: str
    action_kind: WorkflowCleanupActionKind
    artifact_id: str
    node_id: str
    port_name: str
    managed_path: str
    size_bytes: int = Field(ge=0)
    file_sha256: str | None = None
    eligible: bool
    blockers: list[str] = Field(default_factory=list)


class WorkflowArtifactCleanupPreviewResponse(BaseModel):
    workflow_run_id: str
    run_status: str
    preview_checksum: str
    action_count: int = Field(ge=0)
    eligible_action_count: int = Field(ge=0)
    reclaimable_bytes: int = Field(ge=0)
    actions: list[WorkflowArtifactCleanupAction]


class WorkflowArtifactCleanupApplyRequest(BaseModel):
    preview_checksum: str = Field(min_length=64, max_length=64)
    action_ids: list[str] = Field(min_length=1, max_length=10_000)
    node_ids: list[str] = Field(default_factory=list, max_length=1000)


class WorkflowArtifactCleanupApplyResponse(BaseModel):
    workflow_run_id: str
    applied_action_count: int = Field(ge=0)
    quarantined_file_count: int = Field(ge=0)
    cleared_reference_count: int = Field(ge=0)
    reclaimed_bytes: int = Field(ge=0)
    quarantine_paths: list[str]
