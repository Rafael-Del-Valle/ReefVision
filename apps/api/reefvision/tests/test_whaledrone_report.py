import csv
import json
from pathlib import Path

import pytest

from reefvision.geospatial.calibration import CameraCalibration
from reefvision.geospatial.models import TelemetrySample
from reefvision.geospatial.projection import SurfaceReference
from reefvision.geospatial.synchronization import IndexedTelemetrySource
from reefvision.geospatial.validation import (
    GeoreferenceValidationPoint,
    GeoreferenceValidationReport,
    evaluate_georeferencing,
)
from reefvision.tests.whaledrone_georeferencing import WhaleDroneValidationClip
from reefvision.tests.whaledrone_report import (
    build_summary,
    finalize_rows,
    load_annotations,
    observation_rows,
    sanity_checks,
    write_report,
)


def test_report_metrics_exclusions_and_csv_roundtrip(tmp_path: Path) -> None:
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
                gimbal_yaw_deg=0,
                gimbal_pitch_deg=-90,
                gimbal_roll_deg=0,
            )
        ]
    )
    points = [
        GeoreferenceValidationPoint(
            point_id=str(i),
            source_video="synthetic.mp4",
            frame_index=f,
            pixel_x=x,
            pixel_y=400,
            latitude=0,
            longitude=0,
        )
        for i, (f, x) in enumerate([(0, 500), (0, 550), (30, 500)])
    ]
    report = evaluate_georeferencing(
        points=points,
        telemetry_source=source,
        calibration=calibration,
        fps=30,
        surface=SurfaceReference(takeoff_height_above_surface_m=0, evidence="Synthetic"),
        max_delta_s=0.1,
    )
    rows = observation_rows(report)
    summary = build_summary(rows, {"video": "synthetic.mp4", "calibration": "synthetic.json"})
    assert (summary["attempted"], summary["projected"], summary["excluded"]) == (3, 2, 1)
    assert summary["mean_error_m"] == pytest.approx(5, abs=1e-7)
    assert summary["std_error_m"] == pytest.approx(5, abs=1e-7)
    assert summary["rmse_error_m"] == pytest.approx(50**0.5, abs=1e-7)
    assert summary["p95_error_m"] == pytest.approx(9.5, abs=1e-7)
    assert summary["mean_east_error_m"] == pytest.approx(5, abs=1e-7)
    assert summary["mean_north_error_m"] == pytest.approx(0, abs=1e-7)
    assert summary["mean_sync_error_ms"] == 0
    assert summary["all_matched_sync"]["max_sync_error_ms"] == 1000
    assert summary["label"] == "PRELIMINARY VALIDATION"
    assert rows[2]["sync_delta_s"] == -1 and rows[2]["error_m"] is None
    assert summary["diagnostics"]["relative_altitude_m"]["pearson_r"] is None
    checks = sanity_checks(report, calibration)
    assert checks["passed"] and checks["near_nadir_samples_checked"] == 1
    assert checks["max_target_distance_from_drone_m"] == pytest.approx(10, abs=1e-7)
    csv_path, json_path = write_report(tmp_path, rows, summary)
    with csv_path.open() as stream:
        assert len(list(csv.DictReader(stream))) == 3
    assert json.loads(json_path.read_text())["excluded"] == 1


def test_loader_retains_invalid_rows_and_both_sync_identifiers(tmp_path: Path) -> None:
    path = tmp_path / "annotations.csv"
    path.write_text(
        "name,frame,time,video,length,image_x,image_y,lat,lon\n"
        "point,31,1.0,/app/data/internal.mp4,NA,500,400,0,0\n"
        "missing-gps,31,9.0,/app/data/internal.mp4,NA,500,400,,0\n"
        "vector,31,1.0,/app/data/internal.mp4,5,500,400,0,0\n"
        "time-only,,2.0,/app/data/internal.mp4,NA,500,400,0,0\n"
    )
    clip = WhaleDroneValidationClip(
        tmp_path / "original.mp4", tmp_path / "original.SRT", path, "internal.mp4", "synthetic"
    )
    points, excluded, selection = load_annotations(clip, frame_base=1, time_column="time")
    assert len(points) == 2 and len(excluded) == 2
    assert points[0].frame_index == 30 and points[0].video_time_s == 1
    assert points[1].frame_index is None and points[1].video_time_s == 2
    assert all(p.source_video == "original.mp4" for p in points)
    assert "geographic" in excluded[0]["exclusion_reason"]
    assert "vector" in excluded[1]["exclusion_reason"]
    assert selection["matching_source_rows"] == 4
    empty = GeoreferenceValidationReport(
        attempted_count=0, failed_count=0, statistics=None, observations=[]
    )
    rows = finalize_rows(empty, excluded, fps=30)
    assert rows[0]["video_time_s"] == 1
    assert rows[0]["annotation_video_time_s"] == 9
    checks = sanity_checks(empty, None)
    assert not checks["passed"] and checks["evaluated_projection_count"] == 0
    timed_points, _, _ = load_annotations(clip, frame_base=None, time_column="time")
    assert timed_points[0].frame_index is None
    assert timed_points[0].source_frame_number == "31"
    assert timed_points[0].source_time_value == "1.0"


def test_empty_report_does_not_claim_operational_success() -> None:
    summary = build_summary([], {"video": None, "calibration": None})
    assert summary["mean_error_m"] is None and summary["attempted"] == 0
    assert not summary["operationally_projected"]
