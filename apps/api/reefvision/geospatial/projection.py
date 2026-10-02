"""Native OpenCV pixels -> absolute-gimbal attitude -> ENU horizontal surface."""

from math import atan2, cos, degrees, hypot, isclose, isfinite, radians, sin
from typing import Literal, Self

import cv2
import numpy as np
from pydantic import BaseModel, Field, FiniteFloat, model_validator

from reefvision.domain.errors import ValidationError
from reefvision.geospatial.calibration import CameraCalibration
from reefvision.geospatial.geodesy import offset_to_geographic
from reefvision.geospatial.georeferencing_policy import (
    MINIMUM_RAY_DEPRESSION_DEG,
)
from reefvision.geospatial.models import TelemetrySample

Vector3 = tuple[float, float, float]


class SurfaceReference(BaseModel):
    """Supply exactly one measured height or verified relative-altitude datum offset."""

    model_config = {"frozen": True}
    camera_height_m: FiniteFloat | None = Field(default=None, gt=0)
    takeoff_height_above_surface_m: FiniteFloat | None = None
    evidence: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def explicit_height_source(self) -> Self:
        if (self.camera_height_m is None) == (self.takeoff_height_above_surface_m is None):
            raise ValueError("Supply exactly one surface height source")
        if not self.evidence.strip():
            raise ValueError("Surface height evidence cannot be blank")
        return self

    def height_for(self, telemetry: TelemetrySample) -> float:
        height = self.camera_height_m
        if height is None:
            if telemetry.relative_altitude_m is None or self.takeoff_height_above_surface_m is None:
                raise ValidationError("Surface intersection requires a known camera altitude")
            height = telemetry.relative_altitude_m + self.takeoff_height_above_surface_m
        if not isfinite(height) or height <= 0:
            raise ValidationError("Camera height above the surface must be finite and positive")
        return height


class GeoreferenceResult(BaseModel):
    model_config = {"frozen": True}
    latitude: FiniteFloat
    longitude: FiniteFloat
    east_offset_m: FiniteFloat
    north_offset_m: FiniteFloat
    source_pixel_x: FiniteFloat
    source_pixel_y: FiniteFloat
    telemetry_sample_index: int
    telemetry_time_s: FiniteFloat
    camera_height_m: FiniteFloat
    calibration_source_id: str | None
    surface_reference: SurfaceReference
    method: Literal["opencv-dji-enu-flat-wgs84-v2"] = "opencv-dji-enu-flat-wgs84-v2"


def _check_pixel(x: float, y: float, width: int, height: int) -> None:
    if not isfinite(x) or not isfinite(y) or not 0 <= x < width or not 0 <= y < height:
        raise ValidationError("Native pixel must be finite and within the calibration image")


def pixel_to_native(
    x: float,
    y: float,
    *,
    native_width_px: int,
    native_height_px: int,
    resized_width_px: int,
    resized_height_px: int,
    pad_left_px: float = 0,
    pad_top_px: float = 0,
) -> tuple[float, float]:
    """Undo a resize plus known padding; resized dimensions exclude padding.

    Pass actual rounded preprocessing dimensions/padding, not a guessed 640x640
    square. Ultralytics public result boxes already use original coordinates.
    """
    if any(
        isinstance(v, bool) or not isinstance(v, int) or v <= 0
        for v in (native_width_px, native_height_px, resized_width_px, resized_height_px)
    ):
        raise ValidationError("Image dimensions must be positive integers")
    if (
        not all(isfinite(v) for v in (x, y, pad_left_px, pad_top_px))
        or min(pad_left_px, pad_top_px) < 0
    ):
        raise ValidationError("Processed pixel and padding must be finite; padding nonnegative")
    native_x = (x - pad_left_px) * native_width_px / resized_width_px
    native_y = (y - pad_top_px) * native_height_px / resized_height_px
    _check_pixel(native_x, native_y, native_width_px, native_height_px)
    return native_x, native_y


def pixel_to_camera_ray(x_px: float, y_px: float, calibration: CameraCalibration) -> Vector3:
    """Unit ray in OpenCV axes: +x right, +y down, +z forward."""
    _check_pixel(x_px, y_px, calibration.width_px, calibration.height_px)
    k = np.array(
        [
            [calibration.fx_px, 0, calibration.cx_px],
            [0, calibration.fy_px, calibration.cy_px],
            [0, 0, 1],
        ],
        dtype=np.float64,
    )
    distortion = np.array(calibration.distortion_coefficients, dtype=np.float64)
    point = np.array([[[x_px, y_px]]], dtype=np.float64)
    try:
        if distortion.size:
            normalized = cv2.undistortPoints(point, k, distortion).reshape(2)
            x, y = float(normalized[0]), float(normalized[1])
        else:
            x = (x_px - calibration.cx_px) / calibration.fx_px
            y = (y_px - calibration.cy_px) / calibration.fy_px
        if not isfinite(x) or not isfinite(y):
            raise ValidationError("Camera undistortion produced a nonfinite ray")
        if distortion.size:
            restored, _ = cv2.projectPoints(
                np.array([[x, y, 1.0]]),
                np.zeros(3),
                np.zeros(3),
                k,
                distortion,
            )
            error = float(np.linalg.norm(restored.reshape(2) - point.reshape(2)))
            if not isfinite(error) or error > 1e-5:
                raise ValidationError("Camera undistortion did not converge to the input pixel")
    except cv2.error as exc:
        raise ValidationError("OpenCV could not apply camera calibration") from exc
    norm = hypot(x, y, 1)
    if not isfinite(norm):
        raise ValidationError("Camera ray magnitude is invalid")
    return x / norm, y / norm, 1 / norm


def camera_ray_to_enu(ray: Vector3, telemetry: TelemetrySample) -> Vector3:
    """R_ENU_NED Rz(yaw) Ry(pitch) Rx(roll) (z_camera,x_camera,y_camera).

    Angles are absolute gimbal degrees: yaw clockwise from North, pitch up
    positive (nadir -90), roll right-wing-down. Aircraft attitude is not added.
    """
    angles = (telemetry.gimbal_yaw_deg, telemetry.gimbal_pitch_deg, telemetry.gimbal_roll_deg)
    if any(value is None or not isfinite(value) for value in angles):
        raise ValidationError("Projection requires finite absolute gimbal yaw, pitch, and roll")
    if not all(isfinite(value) for value in ray) or not isclose(
        sum(value * value for value in ray), 1, abs_tol=1e-8
    ):
        raise ValidationError("Camera ray must be finite and normalized")
    # Explicit narrowing also documents that missing angles are never zero-filled.
    assert telemetry.gimbal_yaw_deg is not None
    assert telemetry.gimbal_pitch_deg is not None
    assert telemetry.gimbal_roll_deg is not None
    yaw, pitch, roll = map(
        radians, (telemetry.gimbal_yaw_deg, telemetry.gimbal_pitch_deg, telemetry.gimbal_roll_deg)
    )
    forward, right, down = ray[2], ray[0], ray[1]
    right, down = cos(roll) * right - sin(roll) * down, sin(roll) * right + cos(roll) * down
    forward, down = (
        cos(pitch) * forward + sin(pitch) * down,
        -sin(pitch) * forward + cos(pitch) * down,
    )
    north, east = cos(yaw) * forward - sin(yaw) * right, sin(yaw) * forward + cos(yaw) * right
    return east, north, -down


def project_pixel_to_local_surface(
    x_px: float,
    y_px: float,
    calibration: CameraCalibration,
    telemetry: TelemetrySample,
    surface: SurfaceReference,
    *,
    max_distance_m: float = 10000,
    minimum_ray_depression_deg: float = MINIMUM_RAY_DEPRESSION_DEG,
) -> tuple[float, float]:
    if not isfinite(max_distance_m) or max_distance_m <= 0:
        raise ValidationError("Maximum flat-surface distance must be finite and positive")
    if (
        not isfinite(minimum_ray_depression_deg)
        or minimum_ray_depression_deg <= 0
        or minimum_ray_depression_deg >= 90
    ):
        raise ValidationError("Minimum ray depression must be finite and between 0 and 90 degrees")
    if telemetry.digital_zoom_ratio is not None and not isclose(
        telemetry.digital_zoom_ratio,
        calibration.digital_zoom_ratio,
        rel_tol=1e-6,
    ):
        raise ValidationError("Telemetry zoom does not match camera calibration")
    height = surface.height_for(telemetry)
    east, north, up = camera_ray_to_enu(
        pixel_to_camera_ray(x_px, y_px, calibration),
        telemetry,
    )

    if up >= 0:
        raise ValidationError("Camera ray faces upward or is parallel to the surface")

    ray_depression_deg = degrees(
        atan2(
            -up,
            hypot(east, north),
        )
    )

    if ray_depression_deg + 1e-9 < minimum_ray_depression_deg:
        raise ValidationError(
            f"Camera ray depression {ray_depression_deg:.3f} degrees is below "
            f"the {minimum_ray_depression_deg:.3f}-degree minimum required "
            "for stable flat-surface projection"
        )

    scale = -height / up
    offset = east * scale, north * scale
    if not all(isfinite(v) for v in offset) or hypot(*offset) > max_distance_m:
        raise ValidationError("Surface intersection exceeds the permitted local planar distance")
    return offset


def georeference_pixel(
    *,
    pixel_x: float,
    pixel_y: float,
    telemetry: TelemetrySample,
    calibration: CameraCalibration,
    surface: SurfaceReference,
    max_distance_m: float = 10000,
) -> GeoreferenceResult:
    """Project a native, distorted image pixel using explicitly referenced height."""
    if telemetry.latitude is None or telemetry.longitude is None:
        raise ValidationError("Georeferencing requires drone latitude and longitude")
    east, north = project_pixel_to_local_surface(
        pixel_x,
        pixel_y,
        calibration,
        telemetry,
        surface,
        max_distance_m=max_distance_m,
    )
    latitude, longitude = offset_to_geographic(telemetry.latitude, telemetry.longitude, east, north)
    return GeoreferenceResult(
        latitude=latitude,
        longitude=longitude,
        east_offset_m=east,
        north_offset_m=north,
        source_pixel_x=pixel_x,
        source_pixel_y=pixel_y,
        telemetry_sample_index=telemetry.sample_index,
        telemetry_time_s=telemetry.time_s,
        camera_height_m=surface.height_for(telemetry),
        calibration_source_id=calibration.source_id,
        surface_reference=surface,
    )
