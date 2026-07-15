"""Scientific measurements derived from verified mask annotations."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MaskMeasurementResponse(BaseModel):
    mask_annotation_id: str
    image_id: str
    label_class_id: str | None
    geometry_kind: str
    area_pixels: int = Field(ge=1)
    perimeter_pixels: float = Field(ge=0)
    centroid_x: float
    centroid_y: float
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    contained_box_count: int = Field(ge=0)
    contained_box_density_per_1000_pixels: float = Field(ge=0)
