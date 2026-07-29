"""Scientific measurements derived from verified mask annotations."""

from __future__ import annotations

from math import isclose
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

SurfaceModelKind = Literal["none", "extruded", "cylindrical_centerline"]


class MeasurementPoint(BaseModel):
    x: float = Field(ge=0)
    y: float = Field(ge=0)


class MeasurementCalibrationFields(BaseModel):
    distance_per_pixel: float = Field(gt=0)
    unit: str = Field(min_length=1, max_length=32)
    source: str = Field(default="manual", min_length=1, max_length=100)
    reference_length: float | None = Field(default=None, gt=0)
    reference_pixel_length: float | None = Field(default=None, gt=0)
    default_depth: float | None = Field(default=None, gt=0)
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("unit", "source")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Calibration text fields cannot be blank")
        return stripped

    @field_validator("notes")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class MeasurementCalibrationUpdate(MeasurementCalibrationFields):
    @model_validator(mode="after")
    def validate_reference_pair(self) -> MeasurementCalibrationUpdate:
        if (self.reference_length is None) != (self.reference_pixel_length is None):
            raise ValueError(
                "reference_length and reference_pixel_length must be supplied together"
            )
        if self.reference_length is not None and self.reference_pixel_length is not None:
            expected_distance_per_pixel = self.reference_length / self.reference_pixel_length
            if not isclose(
                self.distance_per_pixel,
                expected_distance_per_pixel,
                rel_tol=1e-6,
                abs_tol=1e-12,
            ):
                raise ValueError(
                    "distance_per_pixel must match "
                    "reference_length / reference_pixel_length"
                )
        return self


class MeasurementCalibrationResponse(MeasurementCalibrationFields):
    image_id: str
    calibrated: bool = True


class MaskMeasurementProfileUpdate(BaseModel):
    base_revision: int = Field(ge=1)
    centerline_points: list[MeasurementPoint] = Field(default_factory=list, max_length=10000)
    surface_model: SurfaceModelKind = "none"
    depth_value: float | None = Field(default=None, gt=0)
    diameter_value: float | None = Field(default=None, gt=0)
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def validate_surface_model(self) -> MaskMeasurementProfileUpdate:
        if len(self.centerline_points) == 1:
            raise ValueError("Centerlines require at least two points")
        if self.surface_model == "cylindrical_centerline" and not self.centerline_points:
            raise ValueError("The cylindrical centerline model requires a centerline")
        return self


class MaskMeasurementProfileResponse(BaseModel):
    mask_annotation_id: str
    image_id: str
    revision: int
    centerline_points: list[MeasurementPoint]
    centerline_length_pixels: float
    surface_model: SurfaceModelKind
    depth_value: float | None
    diameter_value: float | None
    notes: str | None


class MeasurementFilterResponse(BaseModel):
    label_class_ids: list[str] = Field(default_factory=list)
    scientific_names: list[str] = Field(default_factory=list)
    state_names: list[str] = Field(default_factory=list)


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
    filters: MeasurementFilterResponse = Field(default_factory=MeasurementFilterResponse)
    calibrated: bool = False
    physical_unit: str | None = None
    distance_per_pixel: float | None = Field(default=None, gt=0)
    area_physical: float | None = Field(default=None, ge=0)
    perimeter_physical: float | None = Field(default=None, ge=0)
    centroid_x_physical: float | None = None
    centroid_y_physical: float | None = None
    contained_box_density_per_square_unit: float | None = Field(default=None, ge=0)
    centerline_points: list[MeasurementPoint] = Field(default_factory=list)
    total_linear_extension_pixels: float = Field(default=0, ge=0)
    total_linear_extension_physical: float | None = Field(default=None, ge=0)
    surface_area_model: SurfaceModelKind = "none"
    surface_area_physical: float | None = Field(default=None, ge=0)
    surface_area_assumptions: list[str] = Field(default_factory=list)


class MeasurementAggregateGroupResponse(BaseModel):
    key: str
    label: str
    mask_count: int = Field(ge=0)
    area_pixels: int = Field(ge=0)
    perimeter_pixels: float = Field(ge=0)
    contained_box_count: int = Field(ge=0)
    density_per_1000_pixels: float = Field(ge=0)
    total_linear_extension_pixels: float = Field(ge=0)
    calibrated_area_by_unit: dict[str, float] = Field(default_factory=dict)
    calibrated_tle_by_unit: dict[str, float] = Field(default_factory=dict)
    surface_area_by_unit: dict[str, float] = Field(default_factory=dict)


class ProjectMeasurementSummaryResponse(BaseModel):
    project_id: str
    mask_count: int = Field(ge=0)
    calibrated_mask_count: int = Field(ge=0)
    area_pixels: int = Field(ge=0)
    perimeter_pixels: float = Field(ge=0)
    contained_box_count: int = Field(ge=0)
    density_per_1000_pixels: float = Field(ge=0)
    total_linear_extension_pixels: float = Field(ge=0)
    calibrated_area_by_unit: dict[str, float] = Field(default_factory=dict)
    calibrated_tle_by_unit: dict[str, float] = Field(default_factory=dict)
    surface_area_by_unit: dict[str, float] = Field(default_factory=dict)
    by_class: list[MeasurementAggregateGroupResponse] = Field(default_factory=list)
    by_species: list[MeasurementAggregateGroupResponse] = Field(default_factory=list)
    by_state: list[MeasurementAggregateGroupResponse] = Field(default_factory=list)
