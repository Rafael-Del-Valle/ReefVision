"""Shared transparent behavior-model feature utilities."""

from __future__ import annotations

from math import sqrt
from typing import Any

from reefvision.domain.errors import ValidationError

ALGORITHM = "standardized_nearest_centroid"
ALGORITHM_VERSION = "0001"

FEATURE_PRESETS: dict[str, tuple[str, ...]] = {
    "track_only": (
        "track.mean_speed_pixels_per_second",
        "track.bbox_area_coefficient_of_variation",
        "track.path_length_per_mean_bbox_diagonal",
    ),
    "track_pose_geometry": (
        "track.mean_speed_pixels_per_second",
        "track.bbox_area_coefficient_of_variation",
        "track.path_length_per_mean_bbox_diagonal",
        "pose.frame_coverage_fraction",
        "pose.mean_landmarks_per_sampled_frame",
        "pose.mean_spread_per_bbox_diagonal",
        "pose.mean_pairwise_distance_per_bbox_diagonal",
    ),
    "track_pose_identity": (
        "track.mean_speed_pixels_per_second",
        "track.bbox_area_coefficient_of_variation",
        "track.path_length_per_mean_bbox_diagonal",
        "pose.frame_coverage_fraction",
        "pose.mean_spread_per_bbox_diagonal",
        "pose.mean_pairwise_distance_per_bbox_diagonal",
        "pose.resolved_identity_fraction",
        "pose.identity_mean_speed_pixels_per_second",
        "pose.identity_continuity_segment_count",
    ),
}


def feature_request() -> dict[str, object]:
    return {
        "include_predicted": False,
        "include_uncertain": True,
        "minimum_landmark_confidence": None,
    }


def feature_vector(
    feature_response: Any,
    feature_names: tuple[str, ...] | list[str],
    *,
    context: str,
) -> list[float]:
    values = {item.name: item for item in feature_response.features}
    result: list[float] = []
    for name in feature_names:
        item = values.get(name)
        if item is None or not item.available or item.value is None:
            reason = (
                item.missing_reason
                if item is not None and item.missing_reason
                else "feature is unavailable"
            )
            raise ValidationError(
                f"Behavior model requires feature '{name}' for {context}: {reason}"
            )
        result.append(float(item.value))
    return result


def standardize(
    vector: list[float],
    feature_names: list[str],
    scaler: dict[str, Any],
) -> list[float]:
    standardized: list[float] = []
    for index, name in enumerate(feature_names):
        entry = scaler.get(name)
        if not isinstance(entry, dict):
            raise ValidationError("Behavior model scaler metadata is incomplete")
        mean = float(entry.get("mean", 0.0))
        std = float(entry.get("std", 0.0))
        if std <= 0:
            raise ValidationError("Behavior model scaler contains an invalid standard deviation")
        standardized.append((vector[index] - mean) / std)
    return standardized


def centroid_distances(
    vector: list[float],
    centroids: dict[str, Any],
) -> dict[str, float]:
    distances: dict[str, float] = {}
    for state_id, raw_centroid in centroids.items():
        if not isinstance(raw_centroid, list) or len(raw_centroid) != len(vector):
            raise ValidationError("Behavior model centroid metadata is incomplete")
        centroid = [float(value) for value in raw_centroid]
        distances[state_id] = sqrt(
            sum((value - centroid[index]) ** 2 for index, value in enumerate(vector))
        )
    if len(distances) < 2:
        raise ValidationError("Behavior model must contain at least two state centroids")
    return distances
