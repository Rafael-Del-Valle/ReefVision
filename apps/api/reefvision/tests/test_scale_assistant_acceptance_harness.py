from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def harness():
    path = (
        Path(__file__).resolve().parents[4]
        / "scripts"
        / "acceptance_scale_assistant.py"
    )
    spec = importlib.util.spec_from_file_location("acceptance_scale_assistant", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _image(tmp_path: Path, name: str = "reference.png") -> Path:
    path = tmp_path / name
    path.write_bytes(b"real-image-placeholder-for-parser-test")
    return path


def _manifest(image_name: str) -> dict[str, object]:
    return {
        "schema_version": "reefvision-scale-assistant-validation-0001",
        "unit": "mm",
        "tolerance": {
            "relative": 0.03,
            "absolute": 0.05,
            "scale_relative": 0.02,
        },
        "cases": [
            {
                "name": "ruler-front",
                "method": "ruler",
                "image": image_name,
                "reference_length": 10.0,
                "expected_distance_per_pixel": 0.1,
                "orientation": "horizontal",
                "probe": {
                    "polygon": [[10, 10], [30, 10], [30, 20], [10, 20]],
                    "centerline": [[10, 15], [30, 15]],
                    "expected": {
                        "area": 2.0,
                        "perimeter": 6.0,
                        "centerline_length": 2.0,
                    },
                },
            }
        ],
    }


def _write_manifest(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "scale-assistant.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_manifest_requires_known_ruler_interval_and_expected_scale(
    harness,
    tmp_path: Path,
) -> None:
    image = _image(tmp_path)
    payload = _manifest(image.name)

    parsed = harness.load_manifest(_write_manifest(tmp_path, payload))

    case = parsed["cases"][0]
    assert case["reference_length"] == 10.0
    assert case["expected_distance_per_pixel"] == 0.1
    assert case["probe"]["expected"]["area"] == 2.0


def test_ruler_manifest_cannot_omit_independent_expected_scale(
    harness,
    tmp_path: Path,
) -> None:
    image = _image(tmp_path)
    payload = _manifest(image.name)
    case = dict(payload["cases"][0])
    case.pop("expected_distance_per_pixel")
    payload["cases"] = [case]

    with pytest.raises(RuntimeError, match="requires expected_distance_per_pixel"):
        harness.load_manifest(_write_manifest(tmp_path, payload))


def test_charuco_manifest_rejects_marker_as_large_as_square(
    harness,
    tmp_path: Path,
) -> None:
    image = _image(tmp_path)
    payload = {
        "schema_version": "reefvision-scale-assistant-validation-0001",
        "unit": "mm",
        "cases": [
            {
                "name": "charuco-oblique",
                "method": "charuco",
                "image": image.name,
                "dictionary": "DICT_4X4_50",
                "marker_length": 10.0,
                "charuco_squares_x": 5,
                "charuco_squares_y": 7,
                "charuco_square_length": 10.0,
            }
        ],
    }

    with pytest.raises(RuntimeError, match="marker_length must be smaller"):
        harness.load_manifest(_write_manifest(tmp_path, payload))


def test_manifest_rejects_negative_tolerance(harness, tmp_path: Path) -> None:
    image = _image(tmp_path)
    payload = _manifest(image.name)
    payload["tolerance"] = {"relative": -0.1}

    with pytest.raises(RuntimeError, match="tolerances cannot be negative"):
        harness.load_manifest(_write_manifest(tmp_path, payload))


def test_measurement_error_accepts_relative_or_absolute_tolerance(harness) -> None:
    relative = harness.measurement_error(
        10.1,
        10.0,
        relative_tolerance=0.02,
        absolute_tolerance=0.0,
    )
    absolute = harness.measurement_error(
        0.03,
        0.02,
        relative_tolerance=0.0,
        absolute_tolerance=0.02,
    )
    outside = harness.measurement_error(
        10.4,
        10.0,
        relative_tolerance=0.02,
        absolute_tolerance=0.0,
    )

    assert relative["within_tolerance"] is True
    assert absolute["within_tolerance"] is True
    assert outside["within_tolerance"] is False


def test_harness_source_requires_researcher_ruler_reference_and_profile_confirmation(
) -> None:
    source = (
        Path(__file__).resolve().parents[4]
        / "scripts"
        / "acceptance_scale_assistant.py"
    ).read_text(encoding="utf-8")

    assert 'candidate["unit_inferred"] is not False' in source
    assert 'candidate["reference_length_required"] is not True' in source
    assert '"confirm_same_setup": True' in source
    assert 'calibration["perspective_homography"] is not None' in source
