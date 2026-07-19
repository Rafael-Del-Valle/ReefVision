"""Raster mask brush, eraser, and cleanup request schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, FiniteFloat, model_validator

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
    mode: Literal["paint", "erase"]
    brush_radius: FiniteFloat = Field(gt=0, le=4096)
    strokes: list[RasterEditStroke] = Field(min_length=1, max_length=10_000)


class RasterMaskCleanupRequest(BaseModel):
    base_revision: int = Field(ge=0)
    mask_annotation_id: str = Field(min_length=1, max_length=36)
    remove_small_components: bool = True
    minimum_component_area: int = Field(default=25, ge=1, le=100_000_000)
    keep_largest_component: bool = False
    fill_holes: bool = False
    connectivity: Literal[4, 8] = 8

    @model_validator(mode="after")
    def require_cleanup_operation(self) -> RasterMaskCleanupRequest:
        if not (
            self.remove_small_components
            or self.keep_largest_component
            or self.fill_holes
        ):
            raise ValueError("Choose at least one raster cleanup operation")
        return self


class RasterMaskEditResponse(BaseModel):
    image: ImageResponse
    mask_annotation: MaskAnnotationResponse
