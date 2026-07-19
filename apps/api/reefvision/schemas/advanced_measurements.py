"""Advanced shape, skeleton, surface, and multi-reference calibration schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, FiniteFloat, field_validator


class CalibrationReference(BaseModel):
    pixel_distance: FiniteFloat = Field(gt=0)
    physical_distance: FiniteFloat = Field(gt=0)
    label: str | None = Field(default=None, max_length=200)


class MultiReferenceCalibrationRequest(BaseModel):
    references: list[CalibrationReference] = Field(min_length=1, max_length=10_000)
    unit: str = Field(min_length=1, max_length=32)
    source: str = Field(default="multi_reference", min_length=1, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("unit", "source")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Calibration text cannot be blank")
        return value


class MultiReferenceCalibrationResponse(BaseModel):
    image_id: str
    distance_per_pixel: float = Field(gt=0)
    unit: str
    reference_count: int = Field(ge=1)
    residual_standard_error: float | None = Field(default=None, ge=0)
    lower_95: float | None = Field(default=None, ge=0)
    upper_95: float | None = Field(default=None, ge=0)
    source: str
    notes: str | None


class AdvancedMeasurementRequest(BaseModel):
    prune_spurs_pixels: FiniteFloat = Field(default=0, ge=0, le=10_000)
    bridge_gaps_pixels: FiniteFloat = Field(default=0, ge=0, le=10_000)
    surface_method: Literal[
        "none",
        "extruded",
        "cylindrical",
        "elliptical_cylinder",
        "pixel_frustum",
    ] = "none"
    depth_value: FiniteFloat | None = Field(default=None, gt=0)
    diameter_major: FiniteFloat | None = Field(default=None, gt=0)
    diameter_minor: FiniteFloat | None = Field(default=None, gt=0)
    pixel_area_scale: FiniteFloat | None = Field(default=None, gt=0)
    uncertainty_fraction: FiniteFloat | None = Field(default=None, ge=0, le=1)


class AdvancedShapeResponse(BaseModel):
    area_pixels: int = Field(ge=1)
    perimeter_pixels: float = Field(ge=0)
    convex_hull_area_pixels: float = Field(ge=0)
    solidity: float = Field(ge=0)
    circularity: float = Field(ge=0)
    compactness: float = Field(ge=0)
    feret_max_pixels: float = Field(ge=0)
    feret_min_pixels: float = Field(ge=0)
    major_axis_pixels: float = Field(ge=0)
    minor_axis_pixels: float = Field(ge=0)
    orientation_degrees: float
    bounding_width_pixels: int = Field(ge=1)
    bounding_height_pixels: int = Field(ge=1)


class AdvancedSkeletonResponse(BaseModel):
    method: str
    skeleton_pixel_count: int = Field(ge=0)
    total_length_pixels: float = Field(ge=0)
    longest_path_pixels: float = Field(ge=0)
    endpoint_count: int = Field(ge=0)
    junction_count: int = Field(ge=0)
    branch_count: int = Field(ge=0)
    branch_lengths_pixels: list[float]
    pruned_pixels: int = Field(ge=0)
    bridged_gaps: int = Field(ge=0)


class AdvancedSurfaceResponse(BaseModel):
    method: str
    area: float | None = Field(default=None, ge=0)
    unit_squared: str | None
    standard_uncertainty: float | None = Field(default=None, ge=0)
    lower_95: float | None = Field(default=None, ge=0)
    upper_95: float | None = Field(default=None, ge=0)
    assumptions: list[str]


class AdvancedMeasurementResponse(BaseModel):
    mask_annotation_id: str
    image_id: str
    revision: int = Field(ge=1)
    calibrated: bool
    distance_per_pixel: float | None = Field(default=None, gt=0)
    physical_unit: str | None
    shape: AdvancedShapeResponse
    skeleton: AdvancedSkeletonResponse
    surface: AdvancedSurfaceResponse
    total_length_physical: float | None = Field(default=None, ge=0)
    longest_path_physical: float | None = Field(default=None, ge=0)
    feret_max_physical: float | None = Field(default=None, ge=0)
    feret_min_physical: float | None = Field(default=None, ge=0)
    warnings: list[str]
