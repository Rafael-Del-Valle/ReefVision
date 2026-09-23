"""Reusable native-image pinhole calibration and external JSON schema adaptation."""

from collections.abc import Mapping
from math import isclose
from typing import Protocol, Self

from pydantic import BaseModel, Field, FiniteFloat, StrictInt, model_validator
from pydantic import ValidationError as SchemaError

from reefvision.domain.errors import ValidationError


class IntrinsicsLike(Protocol):
    @property
    def fx_px(self) -> float: ...
    @property
    def fy_px(self) -> float: ...
    @property
    def cx_px(self) -> float: ...
    @property
    def cy_px(self) -> float: ...


class CameraCalibration(BaseModel):
    """OpenCV native-image intrinsics; distortion must be explicit, even if empty.

    The calibrated zoom is 1 by default (uncropped wide camera). Source ID is
    provenance, not a file to resolve; file loaders supply a content checksum.
    """

    model_config = {"frozen": True}

    width_px: StrictInt = Field(gt=0)
    height_px: StrictInt = Field(gt=0)
    fx_px: FiniteFloat = Field(gt=0)
    fy_px: FiniteFloat = Field(gt=0)
    cx_px: FiniteFloat
    cy_px: FiniteFloat
    distortion_coefficients: tuple[FiniteFloat, ...]
    digital_zoom_ratio: FiniteFloat = Field(default=1, gt=0)
    source_id: str | None = None

    @model_validator(mode="after")
    def valid_distortion(self) -> Self:
        if len(self.distortion_coefficients) not in {0, 4, 5, 8, 12, 14}:
            raise ValueError("OpenCV distortion requires 0, 4, 5, 8, 12, or 14 coefficients")
        return self

    @classmethod
    def from_intrinsics(
        cls,
        intrinsics: IntrinsicsLike,
        *,
        width_px: int,
        height_px: int,
        distortion_coefficients: tuple[float, ...],
        source_id: str | None = None,
        digital_zoom_ratio: float = 1,
    ) -> Self:
        """Adapt existing VideoCameraIntrinsicsResponse/SetRequest without new persistence."""
        return cls(
            width_px=width_px,
            height_px=height_px,
            fx_px=intrinsics.fx_px,
            fy_px=intrinsics.fy_px,
            cx_px=intrinsics.cx_px,
            cy_px=intrinsics.cy_px,
            distortion_coefficients=distortion_coefficients,
            source_id=source_id,
            digital_zoom_ratio=digital_zoom_ratio,
        )


class _Resolution(BaseModel):
    width_px: StrictInt = Field(gt=0)
    height_px: StrictInt = Field(gt=0)


class _Matrix(BaseModel):
    fx: FiniteFloat = Field(gt=0)
    fy: FiniteFloat = Field(gt=0)
    cx: FiniteFloat
    cy: FiniteFloat
    matrix_row_major: (
        tuple[
            tuple[FiniteFloat, FiniteFloat, FiniteFloat],
            tuple[FiniteFloat, FiniteFloat, FiniteFloat],
            tuple[FiniteFloat, FiniteFloat, FiniteFloat],
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def consistent_matrix(self) -> Self:
        expected = ((self.fx, 0, self.cx), (0, self.fy, self.cy), (0, 0, 1))
        if self.matrix_row_major is not None and any(
            not isclose(actual, wanted, rel_tol=1e-10, abs_tol=1e-10)
            for row, target in zip(self.matrix_row_major, expected, strict=True)
            for actual, wanted in zip(row, target, strict=True)
        ):
            raise ValueError(
                "Camera matrix conflicts with scalar intrinsics or has unsupported skew"
            )
        return self


class _Distortion(BaseModel):
    vector_opencv_order: tuple[FiniteFloat, ...]


class _ExternalCalibration(BaseModel):
    image_resolution: _Resolution
    camera_matrix: _Matrix
    distortion_coefficients: _Distortion


def calibration_from_mapping(
    data: Mapping[str, object], *, source_id: str | None = None
) -> CameraCalibration:
    """Accept normalized ReefVision or documented DVM/WhaleDrone calibration JSON."""
    try:
        if "image_resolution" in data:
            external = _ExternalCalibration.model_validate(data)
            k = external.camera_matrix
            return CameraCalibration(
                width_px=external.image_resolution.width_px,
                height_px=external.image_resolution.height_px,
                fx_px=k.fx,
                fy_px=k.fy,
                cx_px=k.cx,
                cy_px=k.cy,
                distortion_coefficients=external.distortion_coefficients.vector_opencv_order,
                source_id=source_id,
            )
        values = dict(data)
        if source_id is not None:
            values["source_id"] = source_id
        return CameraCalibration.model_validate(values)
    except SchemaError as exc:
        raise ValidationError(f"Invalid camera calibration: {exc}") from exc
