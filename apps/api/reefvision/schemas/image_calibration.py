"""Image-scale Auto Calibration request and evidence schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from reefvision.schemas.measurements import (
    CalibrationCameraSignature,
    MeasurementCalibrationUpdate,
)

CalibrationOrientation = Literal["auto", "horizontal", "vertical"]
MarkerKind = Literal["aruco", "charuco"]


class CalibrationRoi(BaseModel):
    x_min: float = Field(ge=0)
    y_min: float = Field(ge=0)
    x_max: float = Field(gt=0)
    y_max: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_bounds(self) -> CalibrationRoi:
        if self.x_max <= self.x_min or self.y_max <= self.y_min:
            raise ValueError("Calibration ROI must have positive width and height")
        return self


class RulerCalibrationDetectRequest(BaseModel):
    roi: CalibrationRoi | None = None
    orientation: CalibrationOrientation = "auto"


class RulerCalibrationCandidate(BaseModel):
    image_id: str
    method: Literal["automatic_ruler"] = "automatic_ruler"
    orientation: Literal["horizontal", "vertical"]
    roi: CalibrationRoi
    base_interval_pixels: float = Field(gt=0)
    major_interval_pixels: float | None = Field(default=None, gt=0)
    tick_positions_pixels: list[float] = Field(default_factory=list)
    interval_count: int = Field(ge=1)
    interval_coefficient_of_variation: float = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    unit_inferred: bool = False
    reference_length_required: bool = True
    warnings: list[str] = Field(default_factory=list)


class ScaleBarCalibrationDetectRequest(BaseModel):
    roi: CalibrationRoi | None = None
    orientation: CalibrationOrientation = "auto"


class ScaleBarCalibrationCandidate(BaseModel):
    image_id: str
    method: Literal["automatic_scale_bar"] = "automatic_scale_bar"
    orientation: Literal["horizontal", "vertical"]
    roi: CalibrationRoi
    bar_start_pixels: tuple[float, float]
    bar_end_pixels: tuple[float, float]
    bar_length_pixels: float = Field(gt=0)
    bar_thickness_pixels: float = Field(gt=0)
    polarity: Literal["dark", "light"]
    continuity_score: float = Field(ge=0, le=1)
    contrast_score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    label_text: str | None = None
    unit_inferred: bool = False
    reference_length_required: bool = True
    warnings: list[str] = Field(default_factory=list)


class MarkerCalibrationDetectRequest(BaseModel):
    kind: MarkerKind = "aruco"
    unit: str = Field(min_length=1, max_length=32)
    dictionary: str = Field(default="DICT_4X4_50", min_length=1, max_length=64)
    marker_length: float = Field(gt=0)
    marker_id: int | None = Field(default=None, ge=0)
    charuco_squares_x: int | None = Field(default=None, ge=3, le=50)
    charuco_squares_y: int | None = Field(default=None, ge=3, le=50)
    charuco_square_length: float | None = Field(default=None, gt=0)

    @field_validator("unit", "dictionary")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Marker calibration text fields cannot be blank")
        return stripped

    @model_validator(mode="after")
    def validate_charuco(self) -> MarkerCalibrationDetectRequest:
        values = (
            self.charuco_squares_x,
            self.charuco_squares_y,
            self.charuco_square_length,
        )
        if self.kind == "charuco":
            if any(value is None for value in values):
                raise ValueError(
                    "ChArUco calibration requires squares_x, squares_y, and square_length"
                )
            square_length = self.charuco_square_length
            if square_length is not None and self.marker_length >= square_length:
                raise ValueError("ChArUco marker_length must be smaller than charuco_square_length")
        return self


class MarkerCalibrationCandidate(BaseModel):
    image_id: str
    method: MarkerKind
    marker_id: int | None = None
    detected_corner_count: int = Field(ge=4)
    confidence: float = Field(ge=0, le=1)
    calibration: MeasurementCalibrationUpdate
    reference_plane_only: bool = True
    corners_pixels: list[list[float]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CalibrationProfileResponse(BaseModel):
    project_id: str
    source_image_id: str
    profile_name: str
    unit: str
    distance_per_pixel: float = Field(gt=0)
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    source: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    camera_signature: CalibrationCameraSignature | None = None
    notes: str | None = None


class ApplyCalibrationProfileRequest(BaseModel):
    source_image_id: str = Field(min_length=36, max_length=36)
    confirm_same_setup: bool = False
    default_depth: float | None = Field(default=None, gt=0)
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None
