"""Advanced provider execution request/response schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AdvancedProviderExecutionRequest(BaseModel):
    task: str = Field(min_length=1, max_length=80)
    device: str = Field(default="auto", min_length=1, max_length=30)
    allow_model_download: bool = False
    prompt_fields: dict[str, Any] = Field(default_factory=dict)


class AdvancedProviderExecutionResponse(BaseModel):
    provider_id: str
    task: str
    status: str = "completed"
    model_id: str | None = None
    model_revision: str | None = None
    result: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)
