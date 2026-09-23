"""Regression tests for the documented ReefVision/DVM projection conventions."""

from __future__ import annotations

from math import atan, cos, radians, sin, tan

import cv2
import numpy as np

from reefvision.geospatial.calibration import CameraCalibration
from reefvision.geospatial.models import TelemetrySample
from reefvision.geospatial.projection import camera_ray_to_enu, pixel_to_camera_ray


def _dvm_camera_ray(
    x_px: float,
    y_px: float,
    calibration: CameraCalibration,
) -> tuple[float, float, float]:
    """Reproduce DVM Fov.get_unit_vector, returned in OpenCV axis order."""

    k = np.array(
        [
            [calibration.fx_px, 0.0, calibration.cx_px],
            [0.0, calibration.fy_px, calibration.cy_px],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )
    distortion = np.asarray(calibration.distortion_coefficients, dtype=np.float64)
    point = np.array([[[x_px, y_px]]], dtype=np.float64)
    undistorted = cv2.undistortPoints(point, k, distortion, P=k)[0, 0]

    horizontal_fov = 2.0 * atan(calibration.width_px / (2.0 * calibration.fx_px))
    vertical_fov = 2.0 * atan(calibration.height_px / (2.0 * calibration.fy_px))
    right = (
        (float(undistorted[0]) - calibration.width_px / 2.0)
        / calibration.width_px
        * (2.0 * tan(horizontal_fov / 2.0))
    )
    forward = 1.0
    up = (
        -(float(undistorted[1]) - calibration.height_px / 2.0)
        / calibration.height_px
        * (2.0 * tan(vertical_fov / 2.0))
    )
    norm = float(np.linalg.norm([right, forward, up]))
    # DVM camera axes are right/forward/up. ReefVision/OpenCV are right/down/forward.
    return right / norm, -up / norm, forward / norm


def _dvm_ray_to_enu(
    ray: tuple[float, float, float],
    *,
    yaw_deg: float,
    pitch_deg: float,
    roll_deg: float,
) -> tuple[float, float, float]:
    """Reproduce DVM Fov.rotation after translating camera axis labels."""

    right, down, forward = ray
    vector = np.array([right, forward, -down], dtype=np.float64)
    yaw = radians(-yaw_deg)
    pitch = radians(pitch_deg)
    roll = radians(roll_deg)
    roll_matrix = np.array(
        [
            [cos(roll), 0.0, sin(roll)],
            [0.0, 1.0, 0.0],
            [-sin(roll), 0.0, cos(roll)],
        ]
    )
    pitch_matrix = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, cos(pitch), -sin(pitch)],
            [0.0, sin(pitch), cos(pitch)],
        ]
    )
    yaw_matrix = np.array(
        [
            [cos(yaw), -sin(yaw), 0.0],
            [sin(yaw), cos(yaw), 0.0],
            [0.0, 0.0, 1.0],
        ]
    )
    rotated = yaw_matrix @ pitch_matrix @ roll_matrix @ vector
    # DVM world vector is easting/northing/up.
    return float(rotated[0]), float(rotated[1]), float(rotated[2])


def _telemetry(yaw: float, pitch: float, roll: float) -> TelemetrySample:
    return TelemetrySample(
        sample_index=0,
        time_s=0.0,
        latitude=0.0,
        longitude=0.0,
        gimbal_yaw_deg=yaw,
        gimbal_pitch_deg=pitch,
        gimbal_roll_deg=roll,
    )


def test_dvm_and_reefvision_rotation_are_equivalent_after_axis_translation() -> None:
    rays = [
        (0.0, 0.0, 1.0),
        (0.2, -0.1, float(np.sqrt(0.95))),
        (-0.3, 0.4, float(np.sqrt(0.75))),
    ]
    attitudes = [
        (0.0, -90.0, 0.0),
        (90.0, -90.0, 0.0),
        (252.5, -67.3, 4.2),
        (15.0, -35.0, -8.0),
    ]
    for ray in rays:
        ray_array = np.asarray(ray, dtype=np.float64)
        normalized = tuple(float(value) for value in ray_array / np.linalg.norm(ray_array))
        for yaw, pitch, roll in attitudes:
            reef = camera_ray_to_enu(normalized, _telemetry(yaw, pitch, roll))
            dvm = _dvm_ray_to_enu(
                normalized,
                yaw_deg=yaw,
                pitch_deg=pitch,
                roll_deg=roll,
            )
            np.testing.assert_allclose(reef, dvm, rtol=0.0, atol=1e-12)


def test_dvm_and_reefvision_rays_match_when_principal_point_is_image_center() -> None:
    calibration = CameraCalibration(
        width_px=3840,
        height_px=2160,
        fx_px=2969.4,
        fy_px=2970.3,
        cx_px=1920.0,
        cy_px=1080.0,
        distortion_coefficients=(0.26049, -0.83362, 0.00045, -0.00025, 0.73529),
    )
    for pixel in [(1920.0, 1080.0), (500.0, 500.0), (3300.0, 1700.0)]:
        reef = pixel_to_camera_ray(*pixel, calibration)
        dvm = _dvm_camera_ray(*pixel, calibration)
        np.testing.assert_allclose(reef, dvm, rtol=0.0, atol=1e-7)


def test_whaledrone_principal_point_explains_dvm_ray_shift() -> None:
    calibration = CameraCalibration(
        width_px=3840,
        height_px=2160,
        fx_px=2969.4,
        fy_px=2970.3,
        cx_px=1968.5,
        cy_px=1116.9,
        distortion_coefficients=(),
    )
    optical_center = (calibration.cx_px, calibration.cy_px)
    reef = pixel_to_camera_ray(*optical_center, calibration)
    dvm = _dvm_camera_ray(*optical_center, calibration)

    np.testing.assert_allclose(reef, (0.0, 0.0, 1.0), rtol=0.0, atol=1e-12)
    assert dvm[0] > 0.016
    assert dvm[1] > 0.012
    assert dvm[2] < 1.0

    right_shift_at_90_m = (
        (calibration.cx_px - calibration.width_px / 2.0) / calibration.fx_px * 90.0
    )
    down_shift_at_90_m = (
        (calibration.cy_px - calibration.height_px / 2.0) / calibration.fy_px * 90.0
    )
    assert 1.46 < right_shift_at_90_m < 1.48
    assert 1.11 < down_shift_at_90_m < 1.13
