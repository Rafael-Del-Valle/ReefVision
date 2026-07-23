"""Raster/polygon conversion, preview, and repair schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from reefvision.schemas.geometry_tools import PolygonGeometry


class UncompressedMaskRle(BaseModel):
    width: int = Field(ge=1, le=100_000)
    height: int = Field(ge=1, le=100_000)
    counts: list[int] = Field(min_length=1, max_length=20_000_000)
    order: Literal["row_major", "coco_fortran"] = "row_major"

    @model_validator(mode="after")
    def validate_counts(self) -> UncompressedMaskRle:
        if any(count < 0 for count in self.counts):
            raise ValueError("RLE counts cannot be negative")
        if sum(self.counts) != self.width * self.height:
            raise ValueError("RLE counts must cover the complete raster")
        return self


class RasterToPolygonRequest(BaseModel):
    raster: UncompressedMaskRle
    simplify_tolerance: float = Field(default=0, ge=0, le=10_000)
    minimum_component_area: int = Field(default=1, ge=1, le=1_000_000_000)
    preserve_holes: bool = True


class PolygonToRasterRequest(BaseModel):
    polygons: list[PolygonGeometry] = Field(min_length=1, max_length=100_000)
    image_width: int = Field(ge=1, le=100_000)
    image_height: int = Field(ge=1, le=100_000)
    rle_order: Literal["row_major", "coco_fortran"] = "row_major"


class MaskConversionQuality(BaseModel):
    foreground_pixels: int = Field(ge=0)
    component_count: int = Field(ge=0)
    hole_count: int = Field(ge=0)
    touches_boundary: bool
    bounds: tuple[int, int, int, int] | None = None


class RasterToPolygonResponse(BaseModel):
    polygons: list[PolygonGeometry]
    cleaned_raster: UncompressedMaskRle
    quality: MaskConversionQuality
    round_trip_iou: float = Field(ge=0, le=1)
    preview_png_base64: str
    warnings: list[str] = Field(default_factory=list)


class PolygonToRasterResponse(BaseModel):
    raster: UncompressedMaskRle
    quality: MaskConversionQuality
    preview_png_base64: str
    warnings: list[str] = Field(default_factory=list)


class PolygonRepairRequest(BaseModel):
    polygons: list[PolygonGeometry] = Field(min_length=1, max_length=100_000)
    image_width: int = Field(ge=1, le=100_000)
    image_height: int = Field(ge=1, le=100_000)
    simplify_tolerance: float = Field(default=0, ge=0, le=10_000)
    preserve_holes: bool = True


class PolygonRepairResponse(BaseModel):
    polygons: list[PolygonGeometry]
    original_self_intersection_count: int = Field(ge=0)
    repaired_self_intersection_count: int = Field(ge=0)
    quality: MaskConversionQuality
    round_trip_iou: float = Field(ge=0, le=1)
    preview_png_base64: str
    warnings: list[str] = Field(default_factory=list)
