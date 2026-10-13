"""Explicit operator-intended segmentation deployment audit contracts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SegmentationPromoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Caller must send null explicitly for the first promotion.
    expected_active_model_id: str | None = Field(...)
    approved_by: str = Field(min_length=2, max_length=100)
    reason: str = Field(min_length=10, max_length=1000)


class SegmentationRollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_active_model_id: str = Field(min_length=1)
    approved_by: str = Field(min_length=2, max_length=100)
    reason: str = Field(min_length=10, max_length=1000)


class SegmentationDeploymentAuditResponse(BaseModel):
    id: str
    status: Literal["succeeded"]
    task: Literal["segment"] = "segment"
    action: Literal["promote", "rollback"]
    evaluation_id: str | None = None
    deployment_id: str | None = None
    active_model_id: str | None
    previous_model_id: str | None
    approved_by: str
    reason: str
    message: str = "Audited manual model-selection change; no application release was published."
