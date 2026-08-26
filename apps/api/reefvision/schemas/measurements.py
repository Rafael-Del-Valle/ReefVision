"""Scientific measurements derived from verified mask annotations."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

SurfaceModelKind = Literal["none", "extruded", "cylindrical_centerline"]


class MeasurementPoint(BaseModel):
    x: float = Field(ge=0)
    y: float = Field(ge=0)


class CalibrationCameraSignature(BaseModel):
    """Optional setup metadata used to make calibration-profile reuse explicit."""

    width_px: int | None = Field(default=None, gt=0)
    height_px: int | None = Field(default=None, gt=0)
    camera_make: str | None = Field(default=None, max_length=100)
    camera_model: str | None = Field(default=None, max_length=150)
    lens_model: str | None = Field(default=None, max_length=150)
    focal_length_mm: float | None = Field(default=None, gt=0)
    capture_distance: float | None = Field(default=None, gt=0)
    setup_notes: str | None = Field(default=None, max_length=500)

    @field_validator(
        "camera_make",
        "camera_model",
        "lens_model",
        "setup_notes",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class MeasurementCalibrationUpdate(BaseModel):
    distance_per_pixel: float = Field(gt=0)
    unit: str = Field(min_length=1, max_length=32)
    source: str = Field(default="manual", min_length=1, max_length=100)
    reference_length: float | None = Field(default=None, gt=0)
    reference_pixel_length: float | None = Field(default=None, gt=0)
    default_depth: float | None = Field(default=None, gt=0)
    notes: str | None = Field(default=None, max_length=1000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    detector: str | None = Field(default=None, max_length=100)
    profile_name: str | None = Field(default=None, max_length=150)
    profile_source_image_id: str | None = Field(default=None, max_length=36)
    camera_signature: CalibrationCameraSignature | None = None
    perspective_homography: list[list[float]] | None = None
    reference_plane_only: bool = True

    @field_validator("unit", "source")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Calibration text fields cannot be blank")
        return stripped

    @field_validator("notes", "detector", "profile_name")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def validate_reference_pair(self) -> MeasurementCalibrationUpdate:
        if (self.reference_length is None) != (self.reference_pixel_length is None):
            raise ValueError(
                "reference_length and reference_pixel_length must be supplied together"
            )
        matrix = self.perspective_homography
        if matrix is not None:
            if len(matrix) != 3 or any(len(row) != 3 for row in matrix):
                raise ValueError("perspective_homography must be a 3x3 matrix")
            if any(not math.isfinite(float(value)) for row in matrix for value in row):
                raise ValueError("perspective_homography values must be finite")
            if all(abs(float(value)) < 1e-15 for value in matrix[2]):
                raise ValueError("perspective_homography has an invalid projective row")
            determinant = (
                matrix[0][0] * (matrix[1][1] * matrix[2][2] - matrix[1][2] * matrix[2][1])
                - matrix[0][1] * (matrix[1][0] * matrix[2][2] - matrix[1][2] * matrix[2][0])
                + matrix[0][2] * (matrix[1][0] * matrix[2][1] - matrix[1][1] * matrix[2][0])
            )
            if not math.isfinite(float(determinant)) or abs(float(determinant)) < 1e-15:
                raise ValueError("perspective_homography must be invertible")
            if not self.reference_plane_only:
                raise ValueError(
                    "perspective_homography is valid only for the calibrated reference plane"
                )
        return self


class MeasurementCalibrationResponse(MeasurementCalibrationUpdate):
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
    perspective_corrected: bool = False
    calibration_source: str | None = None
    calibration_confidence: float | None = Field(default=None, ge=0, le=1)
    calibration_profile_name: str | None = None


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
