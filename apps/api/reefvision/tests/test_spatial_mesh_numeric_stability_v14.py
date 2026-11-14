"""Regression tests for bounded scientific triangle-area calculations."""

from __future__ import annotations

import pytest

from reefvision.services.spatial_mesh_measurements import triangle_area


def test_large_finite_triangle_area_does_not_overflow_intermediate_norm() -> None:
    area = triangle_area((0.0, 0.0, 0.0), (1e100, 0.0, 0.0), (0.0, 1e100, 0.0))
    assert area == pytest.approx(5e199)


def test_degenerate_large_triangle_has_zero_area() -> None:
    area = triangle_area((0.0, 0.0, 0.0), (1e100, 0.0, 0.0), (2e100, 0.0, 0.0))
    assert area == 0.0


def test_true_cross_product_overflow_is_rejected() -> None:
    with pytest.raises(ValueError, match="overflowed"):
        triangle_area((0.0, 0.0, 0.0), (1e200, 0.0, 0.0), (0.0, 1e200, 0.0))
