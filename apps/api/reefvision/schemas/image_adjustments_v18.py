"""Typed source and rendition pins for reversible photometric corrections."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Gain = Annotated[int, Field(strict=True, ge=50, le=200)]
Brightness = Annotated[int, Field(strict=True, ge=-64, le=64)]


class PhotometricParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    red_gain_percent: Gain = 100
    green_gain_percent: Gain = 100
    blue_gain_percent: Gain = 100
    brightness_offset: Brightness = 0
    contrast_percent: Gain = 100


class ImageAdjustmentDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_sha256: Sha256
    parameters: PhotometricParameters


class ImageAdjustmentReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["image-adjustment-0001"] = "image-adjustment-0001"
    method: Literal["rgb8-channel-brightness-contrast-v1"] = "rgb8-channel-brightness-contrast-v1"
    pixel_axes: Literal["raw_source"] = "raw_source"
    project_id: UUID
    image_id: UUID
    original_sha256: Sha256
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    parameters: PhotometricParameters
    rendition_encoding: Literal["png-rgb8-stored-v1"] = "png-rgb8-stored-v1"
    rendition_sha256: Sha256
    rgb_sha256: Sha256


class ImageAdjustmentPin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    recipe_id: UUID
    content_sha256: Sha256
    original_sha256: Sha256
    rendition_sha256: Sha256


class ImageAdjustmentRecord(BaseModel):
    id: UUID
    project_id: UUID
    image_id: UUID
    content_sha256: Sha256
    receipt: ImageAdjustmentReceipt
    created_at: datetime


class ImageAdjustmentPage(BaseModel):
    items: list[ImageAdjustmentRecord]
    total: int
    page: int
    page_size: int
