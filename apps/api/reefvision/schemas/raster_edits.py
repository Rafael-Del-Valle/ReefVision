"""Raster mask brush and eraser request schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, FiniteFloat

from reefvision.schemas.annotations import MaskAnnotationResponse
from reefvision.schemas.images import ImageResponse


class RasterEditPoint(BaseModel):
    x: FiniteFloat
    y: FiniteFloat


class RasterEditStroke(BaseModel):
    points: list[RasterEditPoint] = Field(min_length=1, max_length=100_000)


class RasterMaskEditRequest(BaseModel):
    base_revision: int = Field(ge=0)
    mask_annotation_id: str | None = Field(default=None, min_length=1, max_length=36)
    label_class_id: str = Field(min_length=1, max_length=36)
    mode: Literal["paint", "erase", "fill"]
    brush_radius: FiniteFloat = Field(gt=0, le=4096)
    fill_tolerance: int = Field(default=24, ge=0, le=255)
    strokes: list[RasterEditStroke] = Field(min_length=1, max_length=10_000)


class RasterMaskClassUpdateRequest(BaseModel):
    base_revision: int = Field(ge=0)
    label_class_id: str = Field(min_length=1, max_length=36)


class RasterMaskEditResponse(BaseModel):
    image: ImageResponse
    mask_annotation: MaskAnnotationResponse
