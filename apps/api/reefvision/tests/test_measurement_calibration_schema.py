from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from reefvision.schemas.measurements import MeasurementCalibrationUpdate


def test_reference_calibration_accepts_consistent_scale() -> None:
    calibration = MeasurementCalibrationUpdate(
        distance_per_pixel=0.02,
        unit="mm",
        source="known scale bar",
        reference_length=10.0,
        reference_pixel_length=500.0,
    )

    assert calibration.distance_per_pixel == pytest.approx(0.02)
    assert calibration.reference_length == 10.0
    assert calibration.reference_pixel_length == 500.0


def test_reference_calibration_rejects_contradictory_scale() -> None:
    with pytest.raises(
        PydanticValidationError,
        match="distance_per_pixel must match reference_length / reference_pixel_length",
    ):
        MeasurementCalibrationUpdate(
            distance_per_pixel=0.2,
            unit="mm",
            source="known scale bar",
            reference_length=10.0,
            reference_pixel_length=500.0,
        )


def test_reference_calibration_requires_complete_reference_pair() -> None:
    with pytest.raises(
        PydanticValidationError,
        match="reference_length and reference_pixel_length must be supplied together",
    ):
        MeasurementCalibrationUpdate(
            distance_per_pixel=0.02,
            unit="mm",
            source="known scale bar",
            reference_length=10.0,
        )
