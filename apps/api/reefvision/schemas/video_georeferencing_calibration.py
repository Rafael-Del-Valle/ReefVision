"""Persisted full camera calibration selected for video georeferencing."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, Field, FiniteFloat, StrictInt, field_validator, model_validator


class VideoGeoreferencingCalibrationSetRequest(BaseModel):
    width_px: StrictInt = Field(gt=0)
    height_px: StrictInt = Field(gt=0)
    fx_px: FiniteFloat = Field(gt=0)
    fy_px: FiniteFloat = Field(gt=0)
    cx_px: FiniteFloat
    cy_px: FiniteFloat
    distortion_coefficients: tuple[FiniteFloat, ...] = ()
    digital_zoom_ratio: FiniteFloat = Field(default=1.0, gt=0)
    camera_mode: str = Field(min_length=1, max_length=120)
    source: str = Field(min_length=1, max_length=500)
    evidence: str = Field(min_length=1, max_length=2000)

    @field_validator("camera_mode", "source", "evidence")
    @classmethod
    def strip_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Calibration provenance text cannot be blank")
        return stripped

    @model_validator(mode="after")
    def valid_distortion(self) -> Self:
        if len(self.distortion_coefficients) not in {0, 4, 5, 8, 12, 14}:
            raise ValueError("OpenCV distortion requires 0, 4, 5, 8, 12, or 14 coefficients")
        return self


class VideoGeoreferencingCalibrationResponse(BaseModel):
    schema_version: Literal["video-georeferencing-calibration-0001"]
    video_id: str
    width_px: int
    height_px: int
    fx_px: float
    fy_px: float
    cx_px: float
    cy_px: float
    distortion_coefficients: tuple[float, ...]
    digital_zoom_ratio: float
    camera_mode: str
    source: str
    evidence: str
    checksum_sha256: str = Field(min_length=64, max_length=64)
    calibration_revision: int = Field(ge=1)
    calibration_updated_at: datetime
    video_revision: int
