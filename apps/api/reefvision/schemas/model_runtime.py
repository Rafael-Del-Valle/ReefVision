"""Versioned local inference settings, draft, and review receipt."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Probability = Annotated[FiniteFloat, Field(ge=0, le=1)]
Device = Literal["cpu", "cuda"]


class ExecutionSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device: Device
    confidence_threshold: Probability
    iou_threshold: Probability


class RuntimeDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: UUID
    runtime_id: str = Field(min_length=1, max_length=60)
    device: Device
    confidence_threshold: Probability | None = None
    iou_threshold: Probability | None = None
    prompt: str = Field(default="", max_length=500)


class RuntimeReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["reviewed-model-runtime-0001"] = "reviewed-model-runtime-0001"
    source_project_id: UUID
    source_model_id: UUID
    catalog_id: str
    display_name: str
    checkpoint_sha256: Digest
    file_size_bytes: int = Field(ge=1)
    task: str
    purpose: str
    labels: list[str]
    class_mapping: dict[str, UUID | None]
    applied_image_settings: list[Literal["device", "confidence_threshold", "iou_threshold"]]
    framework: str
    registered_provider_version: str
    provider_id: str
    provider_version: str
    runtime_id: str
    runtime_version: str
    settings: ExecutionSettings
    prompt: str


class RuntimePreview(BaseModel):
    snapshot: RuntimeReceipt
    content_sha256: Digest


class RuntimeConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft: RuntimeDraft
    reviewed_sha256: Digest


class RuntimeSelectionResponse(RuntimePreview):
    id: UUID
    project_id: UUID
    model_id: UUID
    created_at: datetime
