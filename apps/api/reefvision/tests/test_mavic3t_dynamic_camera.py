from __future__ import annotations

import json
from pathlib import Path

import pytest

from reefvision.geospatial.dji_srt import parse_dji_srt
from reefvision.geospatial.mavic3t_camera import (
    mavic3t_calibration_bundle_sha256,
    resolve_mavic3t_frame_camera,
)
from reefvision.geospatial.models import TelemetrySample


def _write_calibration(
    path: Path,
    *,
    fx: float,
    fy: float,
    cx: float = 1920.0,
    cy: float = 1080.0,
) -> None:
    payload = {
        "image_resolution": {
            "width_px": 3840,
            "height_px": 2160,
        },
        "camera_matrix": {
            "fx": fx,
            "fy": fy,
            "cx": cx,
            "cy": cy,
            "matrix_row_major": [
                [fx, 0.0, cx],
                [0.0, fy, cy],
                [0.0, 0.0, 1.0],
            ],
        },
        "distortion_coefficients": {
            "vector_opencv_order": [0.0, 0.0, 0.0, 0.0, 0.0],
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture
def calibration_dir(tmp_path: Path) -> Path:
    _write_calibration(
        tmp_path / "camera_calibration_DJIM3T_RGBwide.json",
        fx=2969.4,
        fy=2970.3,
        cx=1968.5,
        cy=1116.9,
    )
    _write_calibration(
        tmp_path / "camera_calibration_DJIM3T_RGBtele.json",
        fx=17940.0,
        fy=17940.0,
    )
    return tmp_path


def test_m3t_bare_numeric_focal_len_is_parsed() -> None:
    text = "1\n00:00:00,000 --> 00:00:00,100\n[focal_len: 155.6] [dzoom_ratio: 6.48]"

    sample = parse_dji_srt(text)[0]

    assert sample.focal_length_raw == "155.6"
    assert sample.focal_length_mm == pytest.approx(155.6)
    assert sample.digital_zoom_ratio == pytest.approx(6.48)


@pytest.mark.parametrize(
    ("focal", "zoom"),
    [
        (24.0, 1.0),
        (32.4, 1.35),
        (48.0, 2.0),
        (78.48, 3.27),
        (155.52, 6.48),
    ],
)
def test_wide_camera_resolves_across_intermediate_crops(
    calibration_dir: Path,
    focal: float,
    zoom: float,
) -> None:
    sample = TelemetrySample(
        sample_index=1,
        time_s=0.0,
        focal_length_mm=focal,
        digital_zoom_ratio=zoom,
    )

    state = resolve_mavic3t_frame_camera(
        sample,
        pixel_x=3000.0,
        pixel_y=1400.0,
        calibration_dir=calibration_dir,
    )

    assert state is not None
    assert state.optical_camera == "wide"
    assert state.base_focal_equivalent_mm == pytest.approx(24.0)
    assert state.digital_zoom_ratio == pytest.approx(zoom)
    assert state.calibration.fx_px == pytest.approx(2969.4)

    expected_x = 1968.5 + (3000.0 - 1968.5) / zoom
    expected_y = 1116.9 + (1400.0 - 1116.9) / zoom

    assert state.native_pixel_x == pytest.approx(expected_x)
    assert state.native_pixel_y == pytest.approx(expected_y)


@pytest.mark.parametrize(
    ("focal", "zoom"),
    [
        (161.0, 1.0),
        (180.32, 1.12),
        (227.01, 1.41),
        (262.43, 1.63),
    ],
)
def test_tele_camera_resolves_across_intermediate_crops(
    calibration_dir: Path,
    focal: float,
    zoom: float,
) -> None:
    sample = TelemetrySample(
        sample_index=1,
        time_s=0.0,
        focal_length_mm=focal,
        digital_zoom_ratio=zoom,
    )

    state = resolve_mavic3t_frame_camera(
        sample,
        pixel_x=2500.0,
        pixel_y=1250.0,
        calibration_dir=calibration_dir,
    )

    assert state is not None
    assert state.optical_camera == "tele"
    assert state.base_focal_equivalent_mm == pytest.approx(161.0)
    assert state.digital_zoom_ratio == pytest.approx(zoom)
    assert state.calibration.fx_px == pytest.approx(17940.0)

    expected_x = 1920.0 + (2500.0 - 1920.0) / zoom
    expected_y = 1080.0 + (1250.0 - 1080.0) / zoom

    assert state.native_pixel_x == pytest.approx(expected_x)
    assert state.native_pixel_y == pytest.approx(expected_y)


def test_non_m3t_focal_regime_does_not_force_camera_selection(
    calibration_dir: Path,
) -> None:
    sample = TelemetrySample(
        sample_index=1,
        time_s=0.0,
        focal_length_mm=70.0,
        digital_zoom_ratio=1.0,
    )

    state = resolve_mavic3t_frame_camera(
        sample,
        pixel_x=1920.0,
        pixel_y=1080.0,
        calibration_dir=calibration_dir,
    )

    assert state is None


def test_missing_focal_length_keeps_existing_workflow(
    calibration_dir: Path,
) -> None:
    sample = TelemetrySample(
        sample_index=1,
        time_s=0.0,
        digital_zoom_ratio=2.0,
    )

    state = resolve_mavic3t_frame_camera(
        sample,
        pixel_x=1920.0,
        pixel_y=1080.0,
        calibration_dir=calibration_dir,
    )

    assert state is None


def test_m3t_calibration_bundle_hash_changes_with_profile(
    calibration_dir: Path,
) -> None:
    first = mavic3t_calibration_bundle_sha256(calibration_dir)

    tele_path = calibration_dir / "camera_calibration_DJIM3T_RGBtele.json"

    payload = json.loads(tele_path.read_text(encoding="utf-8"))

    payload["camera_matrix"]["fx"] = 18000.0

    tele_path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    second = mavic3t_calibration_bundle_sha256(calibration_dir)

    assert len(first) == 64
    assert len(second) == 64
    assert first != second
