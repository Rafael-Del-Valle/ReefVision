from __future__ import annotations

import pytest

from reefvision.domain.errors import ValidationError
from reefvision.services.scientific_3d_calibration import (
    _validate_independent_source,
    evaluate_depth_validation,
)


def test_independent_validation_qualifies_raw_depth_without_fitting() -> None:
    predicted = {
        ("track-1", 0): 1.00,
        ("track-1", 1): 1.02,
        ("track-1", 2): 1.05,
        ("track-1", 3): 1.08,
        ("track-1", 4): 1.12,
    }
    references = [
        ("track-1", 0, 1.00),
        ("track-1", 1, 1.02),
        ("track-1", 2, 1.05),
        ("track-1", 3, 1.08),
        ("track-1", 4, 1.12),
    ]

    result = evaluate_depth_validation(
        predicted_depths=predicted,
        references=references,
        relative_tolerance=0.05,
        absolute_tolerance_m=0.02,
    )

    assert result["qualified"] is True
    assert result["sample_count"] == 5
    assert result["distinct_frame_count"] == 5
    assert result["reference_depth_span_m"] == pytest.approx(0.12)
    assert result["rmse_m"] == pytest.approx(0.0)


def test_validation_does_not_qualify_insufficient_depth_span() -> None:
    predicted = {("track-1", frame): 1.0 + frame * 0.005 for frame in range(5)}
    references = [("track-1", frame, 1.0 + frame * 0.005) for frame in range(5)]

    result = evaluate_depth_validation(
        predicted_depths=predicted,
        references=references,
        relative_tolerance=0.05,
        absolute_tolerance_m=0.02,
    )

    assert result["all_samples_within_tolerance"] is True
    assert result["coverage_qualified"] is False
    assert result["qualified"] is False


def test_validation_fails_when_raw_model_depth_exceeds_tolerance() -> None:
    predicted = {
        ("track-1", frame): depth for frame, depth in enumerate((1.0, 1.05, 1.1, 1.15, 1.2))
    }
    references = [
        ("track-1", frame, depth) for frame, depth in enumerate((1.0, 1.05, 1.1, 1.15, 1.5))
    ]

    result = evaluate_depth_validation(
        predicted_depths=predicted,
        references=references,
        relative_tolerance=0.05,
        absolute_tolerance_m=0.02,
    )

    assert result["all_samples_within_tolerance"] is False
    assert result["qualified"] is False


def test_validation_rejects_model_output_as_reference_evidence() -> None:
    with pytest.raises(ValidationError, match="independent"):
        _validate_independent_source("Video Depth Anything model output")
