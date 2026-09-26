import json
import math

import cv2
import numpy as np
import pytest
from pydantic import ValidationError as SchemaError

from reefvision.domain.errors import ValidationError
from reefvision.geospatial.calibration import CameraCalibration, calibration_from_mapping
from reefvision.geospatial.geodesy import geodesic_distance_m, offset_to_geographic
from reefvision.geospatial.georeferencing_policy import MINIMUM_RAY_DEPRESSION_DEG
from reefvision.geospatial.models import TelemetrySample
from reefvision.geospatial.projection import (
    SurfaceReference,
    camera_ray_to_enu,
    georeference_pixel,
    pixel_to_camera_ray,
    pixel_to_native,
    project_pixel_to_local_surface,
)
from reefvision.schemas.video_science import VideoCameraIntrinsicsSetRequest
from reefvision.storage.georeferencing import load_camera_calibration


@pytest.fixture
def calibration():
    return CameraCalibration(
        width_px=1000,
        height_px=800,
        fx_px=500,
        fy_px=500,
        cx_px=500,
        cy_px=400,
        distortion_coefficients=(0, 0, 0, 0, 0),
        source_id="synthetic",
    )


@pytest.fixture
def telemetry():
    return TelemetrySample(
        sample_index=1,
        time_s=0,
        latitude=0,
        longitude=0,
        relative_altitude_m=100,
        gimbal_yaw_deg=0,
        gimbal_pitch_deg=-90,
        gimbal_roll_deg=0,
        digital_zoom_ratio=1,
    )


@pytest.fixture
def surface():
    return SurfaceReference(
        takeoff_height_above_surface_m=0, evidence="Synthetic coincident planes"
    )


def synthetic_external_calibration():
    # Schema-compatible synthetic values, not the WhaleDrone calibration asset.
    return {
        "image_resolution": {"width_px": 1000, "height_px": 800},
        "camera_matrix": {
            "fx": 500,
            "fy": 500,
            "cx": 500,
            "cy": 400,
            "matrix_row_major": [[500, 0, 500], [0, 500, 400], [0, 0, 1]],
        },
        "distortion_coefficients": {"vector_opencv_order": [0.01, -0.02, 0.001, 0, 0]},
    }


def test_external_calibration_loader_and_existing_intrinsics(tmp_path):
    path = tmp_path / "synthetic.json"
    path.write_text(json.dumps(synthetic_external_calibration()))
    loaded = load_camera_calibration(path)
    assert loaded.width_px == 1000 and loaded.fx_px == 500
    assert loaded.distortion_coefficients == (0.01, -0.02, 0.001, 0, 0)
    assert loaded.source_id.startswith("sha256:")
    adapted = CameraCalibration.from_intrinsics(
        VideoCameraIntrinsicsSetRequest(fx_px=400, fy_px=450, cx_px=300, cy_px=200),
        width_px=600,
        height_px=400,
        distortion_coefficients=(),
    )
    assert adapted.fx_px == 400 and adapted.fy_px == 450


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"width_px": -1},
        {"fx_px": float("nan")},
        {"distortion_coefficients": [1, 2, 3]},
        {"height_px": 1.5},
    ],
)
def test_invalid_calibration(bad, calibration):
    data = calibration.model_dump()
    if bad:
        data.update(bad)
    else:
        data.pop("fy_px")
    with pytest.raises(ValidationError, match="calibration"):
        calibration_from_mapping(data)


def test_contradictory_matrix_and_malformed_file(tmp_path):
    data = synthetic_external_calibration()
    data["camera_matrix"]["matrix_row_major"][0][0] = 300
    with pytest.raises(ValidationError, match="calibration"):
        calibration_from_mapping(data)
    path = tmp_path / "bad.json"
    path.write_text("not json")
    with pytest.raises(ValidationError, match="calibration"):
        load_camera_calibration(path)


def test_camera_ray_axes(calibration):
    assert pixel_to_camera_ray(500, 400, calibration) == pytest.approx((0, 0, 1))
    left = pixel_to_camera_ray(400, 400, calibration)
    right = pixel_to_camera_ray(600, 400, calibration)
    assert left[0] == pytest.approx(-right[0])
    assert pixel_to_camera_ray(500, 300, calibration)[1] < 0
    assert pixel_to_camera_ray(500, 500, calibration)[1] > 0
    assert sum(x * x for x in right) == pytest.approx(1)


def test_distortion_inversion_recovers_known_ray(calibration):
    calibration = calibration.model_copy(
        update={"distortion_coefficients": (0.12, -0.04, 0.001, -0.002, 0.01)}
    )
    k = np.array([[500.0, 0, 500], [0, 500, 400], [0, 0, 1]])
    pixel, _ = cv2.projectPoints(
        np.array([[0.3, -0.2, 1.0]]),
        np.zeros(3),
        np.zeros(3),
        k,
        np.array(calibration.distortion_coefficients),
    )
    ray = pixel_to_camera_ray(*pixel.reshape(2), calibration)
    assert ray == pytest.approx(np.array([0.3, -0.2, 1]) / math.sqrt(1.13), abs=1e-9)


def test_native_resize_and_letterbox_restoration():
    args = dict(
        native_width_px=1000, native_height_px=800, resized_width_px=500, resized_height_px=400
    )
    assert pixel_to_native(250, 200, **args) == (500, 400)
    assert pixel_to_native(250, 250, pad_top_px=50, **args) == (500, 400)
    with pytest.raises(ValidationError, match="pixel"):
        pixel_to_native(20, 10, pad_top_px=50, **args)


def test_nadir_center_and_metric_offsets(calibration, telemetry, surface):
    center = georeference_pixel(
        pixel_x=500, pixel_y=400, telemetry=telemetry, calibration=calibration, surface=surface
    )
    assert center.latitude == pytest.approx(0, abs=1e-12)
    assert center.longitude == pytest.approx(0, abs=1e-12)
    assert center.source_pixel_x == 500 and center.calibration_source_id == "synthetic"
    east, north = project_pixel_to_local_surface(550, 350, calibration, telemetry, surface)
    assert (east, north) == pytest.approx((10, 10), abs=1e-10)


@pytest.mark.parametrize(
    ("yaw", "expected"), [(0, (0, 100)), (90, (100, 0)), (180, (0, -100)), (270, (-100, 0))]
)
def test_oblique_yaw_and_pitch(calibration, telemetry, surface, yaw, expected):
    pose = telemetry.model_copy(update={"gimbal_yaw_deg": yaw, "gimbal_pitch_deg": -45})
    assert project_pixel_to_local_surface(500, 400, calibration, pose, surface) == pytest.approx(
        expected, abs=1e-10
    )


def test_roll_rotation_and_nadir_camera_basis(calibration, telemetry, surface):
    pose = telemetry.model_copy(update={"gimbal_roll_deg": 90})
    assert project_pixel_to_local_surface(550, 400, calibration, pose, surface) == pytest.approx(
        (0, -10), abs=1e-10
    )
    assert camera_ray_to_enu((0, 0, 1), telemetry) == pytest.approx((0, 0, -1), abs=1e-12)


def test_combined_angles_preserve_rotation_order(calibration, telemetry, surface):
    pose = telemetry.model_copy(
        update={"gimbal_yaw_deg": 90, "gimbal_pitch_deg": -45, "gimbal_roll_deg": 90}
    )
    # Body (1, .1, 0) -> roll (1, 0, .1) -> pitch (.9, 0, 1.1)/sqrt(2).
    # Yaw turns forward to East, so surface East/height = .9/1.1.
    assert project_pixel_to_local_surface(550, 400, calibration, pose, surface) == pytest.approx(
        (100 * 9 / 11, 0), abs=1e-10
    )


@pytest.mark.parametrize("pixel", [(-1, 400), (1000, 400), (500, 800), (float("nan"), 0)])
def test_out_of_bounds_or_nonfinite_pixels_rejected(calibration, pixel):
    with pytest.raises(ValidationError, match="pixel"):
        pixel_to_camera_ray(*pixel, calibration)


def test_explicit_surface_datum_and_range_limit(calibration, telemetry):
    surface = SurfaceReference(takeoff_height_above_surface_m=5, evidence="Synthetic 5 m datum")
    assert project_pixel_to_local_surface(550, 400, calibration, telemetry, surface)[
        0
    ] == pytest.approx(10.5)
    with pytest.raises(ValidationError, match="distance"):
        project_pixel_to_local_surface(550, 400, calibration, telemetry, surface, max_distance_m=10)


@pytest.mark.parametrize(
    ("pitch_deg", "accepted"),
    [
        (-7.999, False),
        (-8.000, True),
        (-8.001, True),
    ],
)
def test_minimum_ray_depression_stability_guard(
    calibration,
    telemetry,
    surface,
    pitch_deg,
    accepted,
):
    pose = telemetry.model_copy(update={"gimbal_pitch_deg": pitch_deg})

    if accepted:
        east, north = project_pixel_to_local_surface(
            500,
            400,
            calibration,
            pose,
            surface,
        )
        assert math.isfinite(east)
        assert math.isfinite(north)
    else:
        with pytest.raises(
            ValidationError,
            match="minimum required for stable flat-surface projection",
        ):
            project_pixel_to_local_surface(
                500,
                400,
                calibration,
                pose,
                surface,
            )


def test_default_minimum_ray_depression_is_eight_degrees():
    assert pytest.approx(8.0) == MINIMUM_RAY_DEPRESSION_DEG


@pytest.mark.parametrize("pitch", [0, 45, -0.0000001])
def test_upward_parallel_or_near_parallel_ray_rejected(calibration, telemetry, surface, pitch):
    pose = telemetry.model_copy(update={"gimbal_pitch_deg": pitch})
    with pytest.raises(ValidationError):
        project_pixel_to_local_surface(500, 400, calibration, pose, surface)


@pytest.mark.parametrize(
    "field",
    [
        "latitude",
        "longitude",
        "relative_altitude_m",
        "gimbal_yaw_deg",
        "gimbal_pitch_deg",
        "gimbal_roll_deg",
    ],
)
def test_missing_telemetry_rejected(calibration, telemetry, surface, field):
    pose = telemetry.model_copy(update={field: None})
    with pytest.raises(ValidationError):
        georeference_pixel(
            pixel_x=500, pixel_y=400, calibration=calibration, telemetry=pose, surface=surface
        )


def test_surface_reference_is_explicit_and_zoom_must_match(calibration, telemetry):
    with pytest.raises(SchemaError):
        SurfaceReference(evidence="No height supplied")
    surface = SurfaceReference(camera_height_m=25, evidence="Independent height measurement")
    assert project_pixel_to_local_surface(550, 400, calibration, telemetry, surface)[
        0
    ] == pytest.approx(2.5)
    with pytest.raises(ValidationError, match="zoom"):
        georeference_pixel(
            pixel_x=550,
            pixel_y=400,
            calibration=calibration,
            surface=surface,
            telemetry=telemetry.model_copy(update={"digital_zoom_ratio": 2}),
        )


def test_geographic_equatorial_displacement_and_dateline():
    lat, lon = offset_to_geographic(0, 0, 1000, 0)
    assert lat == pytest.approx(0, abs=1e-12)
    assert lon == pytest.approx(0.008983152841195, abs=1e-12)
    lat, lon = offset_to_geographic(0, 0, 0, 1000)
    assert lat == pytest.approx(0.00904369476975, abs=1e-11)
    assert geodesic_distance_m(0, 0, lat, lon) == pytest.approx(1000, abs=1e-8)
    lat, lon = offset_to_geographic(10, 179.999, 1000, 0)
    assert -180 <= lon < -179.9
