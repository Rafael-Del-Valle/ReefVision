from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from reefvision.schemas.image_calibration import MarkerCalibrationDetectRequest
from reefvision.schemas.measurements import (
    MaskMeasurementResponse,
    MeasurementCalibrationUpdate,
)
from reefvision.services.mask_measurements import (
    MaskMeasurementService as BaseMaskMeasurementService,
)
from reefvision.services.scientific_mask_measurements import (
    ScientificMaskMeasurementService,
)


def _raster_response() -> MaskMeasurementResponse:
    return MaskMeasurementResponse(
        mask_annotation_id="mask-1",
        image_id="image-1",
        label_class_id=None,
        geometry_kind="raster_mask",
        area_pixels=100,
        perimeter_pixels=40.0,
        centroid_x=20.0,
        centroid_y=10.0,
        x_min=10.0,
        y_min=5.0,
        x_max=30.0,
        y_max=15.0,
        contained_box_count=0,
        contained_box_density_per_1000_pixels=0.0,
        calibrated=True,
        physical_unit="cm",
        distance_per_pixel=0.1,
        area_physical=1.0,
        perimeter_physical=4.0,
        centroid_x_physical=99.0,
        centroid_y_physical=88.0,
        contained_box_density_per_square_unit=0.0,
        centerline_points=[],
        total_linear_extension_pixels=0.0,
        total_linear_extension_physical=0.0,
        surface_area_model="none",
        surface_area_physical=None,
        surface_area_assumptions=[],
        perspective_corrected=False,
        calibration_source="charuco",
        calibration_confidence=0.95,
        calibration_profile_name=None,
    )


def test_raster_measurements_remain_entirely_scalar_when_homography_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_measure(
        self: BaseMaskMeasurementService,
        mask_annotation_id: str,
        *,
        label_class_ids: list[str] | None = None,
        scientific_names: list[str] | None = None,
        state_names: list[str] | None = None,
    ) -> MaskMeasurementResponse:
        del self, mask_annotation_id, label_class_ids, scientific_names, state_names
        return _raster_response()

    monkeypatch.setattr(BaseMaskMeasurementService, "measure", fake_measure)
    service = ScientificMaskMeasurementService.__new__(ScientificMaskMeasurementService)

    result = service.measure("mask-1")

    assert result.perspective_corrected is False
    assert result.area_physical == pytest.approx(1.0)
    assert result.perimeter_physical == pytest.approx(4.0)
    assert result.centroid_x_physical == pytest.approx(2.0)
    assert result.centroid_y_physical == pytest.approx(1.0)


def test_singular_perspective_homography_is_rejected_before_persistence() -> None:
    with pytest.raises(PydanticValidationError, match="must be invertible"):
        MeasurementCalibrationUpdate(
            distance_per_pixel=0.1,
            unit="cm",
            source="charuco",
            perspective_homography=[
                [1.0, 0.0, 0.0],
                [2.0, 0.0, 0.0],
                [0.0, 0.0, 1.0],
            ],
            reference_plane_only=True,
        )


def test_homography_cannot_claim_non_planar_metric_validity() -> None:
    with pytest.raises(PydanticValidationError, match="reference plane"):
        MeasurementCalibrationUpdate(
            distance_per_pixel=0.1,
            unit="cm",
            source="aruco",
            perspective_homography=[
                [0.1, 0.0, 0.0],
                [0.0, 0.1, 0.0],
                [0.0, 0.0, 1.0],
            ],
            reference_plane_only=False,
        )


def test_charuco_marker_must_be_smaller_than_board_square() -> None:
    with pytest.raises(PydanticValidationError, match="marker_length must be smaller"):
        MarkerCalibrationDetectRequest(
            kind="charuco",
            unit="mm",
            marker_length=10,
            charuco_squares_x=5,
            charuco_squares_y=7,
            charuco_square_length=10,
        )
