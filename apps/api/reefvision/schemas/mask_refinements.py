"""Explicit preview, replacement and history contracts for existing masks."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from reefvision.schemas.assist import AssistPoint


class MaskRefinementPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    variant: Literal["tiny", "small", "base-plus", "large"] = "small"
    device: Literal["auto", "cpu", "cuda", "mps"] = "auto"
    positive_points: list[AssistPoint] = Field(default_factory=list, max_length=32)
    negative_points: list[AssistPoint] = Field(default_factory=list, max_length=32)


class MaskRefinementAcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    confirm_large_change: bool = False


class MaskRefinementGeometryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mask_png_base64: str = Field(min_length=1, max_length=24_000_000)


class MaskRefinementResponse(BaseModel):
    candidate_id: str
    mask_annotation_id: str
    image_id: str
    expected_revision: int
    status: Literal["pending", "accepted", "discarded", "undone"]
    mask_url: str
    old_area_pixels: int
    proposed_area_pixels: int
    iou: float
    edge_change_percent: float
    warnings: list[str]
    requires_confirmation: bool
    expires_at: datetime
