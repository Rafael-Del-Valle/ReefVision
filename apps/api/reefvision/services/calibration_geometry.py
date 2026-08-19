"""Perspective-aware geometry helpers for calibrated measurements."""

from __future__ import annotations

from itertools import pairwise
from math import hypot, isfinite

from reefvision.domain.errors import ValidationError
from reefvision.schemas.measurements import MeasurementPoint

Point = tuple[float, float]
Homography = list[list[float]]


def transform_point(matrix: Homography, point: Point) -> Point:
    """Map an image pixel point into physical reference-plane coordinates."""

    if len(matrix) != 3 or any(len(row) != 3 for row in matrix):
        raise ValidationError("Perspective homography must be a 3x3 matrix")
    x, y = point
    denominator = matrix[2][0] * x + matrix[2][1] * y + matrix[2][2]
    if not isfinite(denominator) or abs(denominator) < 1e-12:
        raise ValidationError("Perspective homography is singular at the requested point")
    transformed_x = (matrix[0][0] * x + matrix[0][1] * y + matrix[0][2]) / denominator
    transformed_y = (matrix[1][0] * x + matrix[1][1] * y + matrix[1][2]) / denominator
    if not isfinite(transformed_x) or not isfinite(transformed_y):
        raise ValidationError("Perspective homography produced non-finite coordinates")
    return transformed_x, transformed_y


def transform_points(matrix: Homography, points: list[Point]) -> list[Point]:
    return [transform_point(matrix, point) for point in points]


def polygon_measurements_float(points: list[Point]) -> tuple[float, float, float, float]:
    """Return area, perimeter, centroid x/y without pixel-area rounding."""

    if len(points) < 3:
        raise ValidationError("A calibrated polygon requires at least three points")
    signed_double_area = sum(
        points[index][0] * points[(index + 1) % len(points)][1]
        - points[(index + 1) % len(points)][0] * points[index][1]
        for index in range(len(points))
    )
    if abs(signed_double_area) < 1e-12:
        raise ValidationError("Calibrated polygon has zero area")
    area = abs(signed_double_area) / 2.0
    centroid_x = sum(
        (points[index][0] + points[(index + 1) % len(points)][0])
        * (
            points[index][0] * points[(index + 1) % len(points)][1]
            - points[(index + 1) % len(points)][0] * points[index][1]
        )
        for index in range(len(points))
    ) / (3.0 * signed_double_area)
    centroid_y = sum(
        (points[index][1] + points[(index + 1) % len(points)][1])
        * (
            points[index][0] * points[(index + 1) % len(points)][1]
            - points[(index + 1) % len(points)][0] * points[index][1]
        )
        for index in range(len(points))
    ) / (3.0 * signed_double_area)
    perimeter = sum(
        hypot(
            points[index][0] - points[(index + 1) % len(points)][0],
            points[index][1] - points[(index + 1) % len(points)][1],
        )
        for index in range(len(points))
    )
    return area, perimeter, centroid_x, centroid_y


def transformed_centerline_length(matrix: Homography, points: list[MeasurementPoint]) -> float:
    if len(points) < 2:
        return 0.0
    transformed = transform_points(matrix, [(point.x, point.y) for point in points])
    return sum(
        hypot(second[0] - first[0], second[1] - first[1])
        for first, second in pairwise(transformed)
    )
