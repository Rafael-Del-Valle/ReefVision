from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def harness():
    path = Path(__file__).resolve().parents[4] / "scripts" / "acceptance_physical_calibration.py"
    spec = importlib.util.spec_from_file_location("acceptance_physical_calibration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _reference_payload() -> dict[str, object]:
    return {
        "schema_version": "reefvision-physical-calibration-validation-0001",
        "spatial_reference": {
            "unit": "cm",
            "reference_distance": 10.0,
            "reference_pixels": 500.0,
        },
        "track": {
            "class_name": "Calibration target",
            "keyframes": [
                {"frame": 0, "bbox": [100, 100, 20, 20]},
                {"frame": 10, "bbox": [200, 100, 20, 20]},
            ],
            "expected_2d": {
                "path_length": 2.0,
                "displacement": 2.0,
                "mean_speed_per_second": 2.0,
            },
        },
        "camera_intrinsics": {
            "fx_px": 1000.0,
            "fy_px": 1000.0,
            "cx_px": 320.0,
            "cy_px": 240.0,
        },
        "metric_depth": {
            "is_metric": True,
            "source": "stereo triangulation with calibrated baseline",
            "unit": "m",
            "samples": [
                {"frame": 0, "depth": 2.0},
                {"frame": 10, "depth": 2.0},
            ],
            "expected_3d": {
                "path_length_3d": 0.2,
                "displacement_3d": 0.2,
                "mean_speed_3d_per_second": 0.2,
                "mean_depth": 2.0,
            },
        },
        "tolerance": {"relative": 0.02, "absolute": 0.001},
    }


def _write_reference(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "reference.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_reference_parser_requires_explicit_metric_measurements(
    harness,
    tmp_path: Path,
) -> None:
    payload = harness.load_reference(_write_reference(tmp_path, _reference_payload()))

    assert payload["spatial_reference"]["unit"] == "cm"
    assert payload["metric_depth"]["unit"] == "m"
    assert payload["metric_depth"]["is_metric"] is True
    assert payload["metric_depth"]["source"] == ("stereo triangulation with calibrated baseline")
    assert payload["metric_depth"]["samples"][0]["depth"] == 2.0


def test_reference_parser_rejects_missing_metric_declaration(
    harness,
    tmp_path: Path,
) -> None:
    payload = _reference_payload()
    metric_depth = dict(payload["metric_depth"])
    metric_depth.pop("is_metric")
    payload["metric_depth"] = metric_depth

    with pytest.raises(RuntimeError, match="is_metric must be true"):
        harness.load_reference(_write_reference(tmp_path, payload))


def test_reference_parser_rejects_relative_monocular_metric_claim(
    harness,
    tmp_path: Path,
) -> None:
    payload = _reference_payload()
    metric_depth = dict(payload["metric_depth"])
    metric_depth["source"] = "Depth Anything V2 relative monocular depth"
    payload["metric_depth"] = metric_depth

    with pytest.raises(RuntimeError, match="cannot be used as metric-depth"):
        harness.load_reference(_write_reference(tmp_path, payload))


def test_reference_parser_rejects_depth_samples_outside_track_range(
    harness,
    tmp_path: Path,
) -> None:
    payload = _reference_payload()
    metric_depth = dict(payload["metric_depth"])
    metric_depth["samples"] = [
        {"frame": 0, "depth": 2.0},
        {"frame": 11, "depth": 2.0},
    ]
    payload["metric_depth"] = metric_depth

    with pytest.raises(RuntimeError, match="verified track frame range"):
        harness.load_reference(_write_reference(tmp_path, payload))


def test_reference_parser_rejects_nonpositive_reference_distance(
    harness,
    tmp_path: Path,
) -> None:
    payload = _reference_payload()
    spatial_reference = dict(payload["spatial_reference"])
    spatial_reference["reference_distance"] = 0
    payload["spatial_reference"] = spatial_reference

    with pytest.raises(RuntimeError, match="finite and positive"):
        harness.load_reference(_write_reference(tmp_path, payload))


def test_measurement_error_applies_relative_or_absolute_tolerance(harness) -> None:
    within_relative = harness.measurement_error(
        10.1,
        10.0,
        relative_tolerance=0.02,
        absolute_tolerance=0.0,
    )
    within_absolute = harness.measurement_error(
        0.03,
        0.02,
        relative_tolerance=0.0,
        absolute_tolerance=0.02,
    )
    outside = harness.measurement_error(
        10.3,
        10.0,
        relative_tolerance=0.02,
        absolute_tolerance=0.0,
    )

    assert within_relative["within_tolerance"] is True
    assert within_absolute["within_tolerance"] is True
    assert outside["within_tolerance"] is False


def test_harness_source_keeps_relative_monocular_depth_nonmetric() -> None:
    source = (
        Path(__file__).resolve().parents[4] / "scripts" / "acceptance_physical_calibration.py"
    ).read_text(encoding="utf-8")
    assert '"relative_monocular_depth_is_metric": False' in source
