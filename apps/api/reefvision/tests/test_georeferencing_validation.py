import pytest

from reefvision.geospatial.calibration import CameraCalibration
from reefvision.geospatial.models import TelemetrySample
from reefvision.geospatial.projection import SurfaceReference
from reefvision.geospatial.synchronization import IndexedTelemetrySource
from reefvision.geospatial.validation import (
    GeoreferenceValidationPoint,
    evaluate_georeferencing,
    summarize_errors,
)


def test_known_error_statistics() -> None:
    stats = summarize_errors([0, 1, 2, 3, 4])
    assert stats.sample_count == 5
    assert stats.mean_m == 2 and stats.median_m == 2
    assert stats.rmse_m == pytest.approx(6**0.5)
    assert stats.min_m == 0 and stats.max_m == 4
    assert stats.p95_m == pytest.approx(3.8)
    assert stats.std_m == pytest.approx(2**0.5)  # Population standard deviation.


def test_validation_reports_successes_sync_failures_and_projection_failures() -> None:
    calibration = CameraCalibration(
        width_px=1000,
        height_px=800,
        fx_px=500,
        fy_px=500,
        cx_px=500,
        cy_px=400,
        distortion_coefficients=(),
    )
    source = IndexedTelemetrySource(
        [
            TelemetrySample(
                sample_index=1,
                time_s=0,
                latitude=0,
                longitude=0,
                relative_altitude_m=100,
                gimbal_pitch_deg=-90,
                gimbal_yaw_deg=0,
                gimbal_roll_deg=0,
            ),
            TelemetrySample(
                sample_index=2, time_s=1, latitude=0, longitude=0, relative_altitude_m=100
            ),
        ]
    )

    def point(identifier, frame):
        return GeoreferenceValidationPoint(
            point_id=identifier,
            frame_index=frame,
            pixel_x=550,
            pixel_y=400,
            latitude=0,
            longitude=0.00008983152841195215,
        )

    report = evaluate_georeferencing(
        points=[point("valid", 0), point("missing-attitude", 30), point("stale", 90)],
        telemetry_source=source,
        calibration=calibration,
        fps=30,
        surface=SurfaceReference(takeoff_height_above_surface_m=0, evidence="Synthetic"),
        max_delta_s=0.05,
    )
    assert report.attempted_count == 3 and report.failed_count == 2
    assert report.statistics.sample_count == 1 and report.statistics.max_m < 1e-8
    assert report.observations[0].sync_delta_s == 0
    assert report.observations[1].error is not None
    assert "sync" in report.observations[2].error.lower()
    assert report.observations[2].sync_delta_s == -2
    assert report.observations[2].sync_error_s == 2
    assert report.observations[2].telemetry.time_s == 1


def test_empty_error_statistics_do_not_fabricate_zero_accuracy() -> None:
    assert summarize_errors([]) is None


def test_relative_time_and_frame_precedence_keep_original_time() -> None:
    calibration = CameraCalibration(
        width_px=1000,
        height_px=800,
        fx_px=500,
        fy_px=500,
        cx_px=500,
        cy_px=400,
        distortion_coefficients=(),
    )
    source = IndexedTelemetrySource(
        [
            TelemetrySample(
                sample_index=i,
                time_s=t,
                latitude=0,
                longitude=0,
                gimbal_yaw_deg=0,
                gimbal_pitch_deg=-90,
                gimbal_roll_deg=0,
            )
            for i, t in enumerate([0.0, 0.2])
        ]
    )
    points = [
        GeoreferenceValidationPoint(
            point_id="both",
            source_video="test.mp4",
            frame_index=3,
            video_time_s=0.9,
            pixel_x=500,
            pixel_y=400,
            latitude=0,
            longitude=0,
        ),
        GeoreferenceValidationPoint(
            point_id="time",
            source_video="test.mp4",
            video_time_s=0.3,
            pixel_x=500,
            pixel_y=400,
            latitude=0,
            longitude=0,
        ),
    ]
    report = evaluate_georeferencing(
        points=points,
        telemetry_source=source,
        calibration=calibration,
        fps=30,
        surface=SurfaceReference(camera_height_m=100, evidence="Synthetic"),
        max_delta_s=0.1,
    )
    assert report.failed_count == 0
    first, second = report.observations
    assert first.video_time_s == pytest.approx(0.1)
    assert first.point.video_time_s == 0.9  # Retained, not silently rewritten.
    assert first.telemetry.time_s == 0  # Earlier sample wins an exact tie.
    assert second.video_time_s == 0.3 and second.telemetry.time_s == 0.2
    assert first.east_error_m == pytest.approx(0, abs=1e-8)
    assert first.north_error_m == pytest.approx(0, abs=1e-8)
