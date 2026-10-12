"""Bounded, class-agnostic automatic SAM image proposals."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SamImageProposalsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    image_id: UUID
    variant: Literal["tiny", "small", "base-plus", "large"] = "tiny"
    device: Literal["auto", "cpu", "cuda"] = "auto"
    generation_policy: Literal["point_grid"] = "point_grid"
    points_per_side: int = Field(default=4, ge=1, le=8)
    tile_size: int = Field(default=1536, ge=512, le=2048)
    min_region_area: int = Field(default=16, ge=1, le=1_000_000)
    confidence_threshold: float = Field(default=0.7, ge=0, le=1)
    stability_threshold: float = Field(default=0.8, ge=0, le=1)
    max_candidates: int = Field(default=32, ge=1, le=64)
    proposal_iou_threshold: float = Field(default=0.85, gt=0, le=1)
    verified_iou_threshold: float = Field(default=0.8, gt=0, le=1)
    timeout_seconds: int = Field(default=120, ge=10, le=600)
