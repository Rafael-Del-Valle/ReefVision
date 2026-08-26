"""Scientific 3D depth sampling and validity helpers for ReefVision video analysis."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import exp
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray

ScientificDepthTier = Literal[
    "relative_depth",
    "model_estimated_metric",
    "calibrated_metric",
    "stereo_metric",
]


@dataclass(frozen=True, slots=True)
class RobustDepthEstimate:
    depth: float
    confidence: float
    valid_fraction: float
    robust_relative_spread: float
    sample_count: int


@dataclass(frozen=True, slots=True)
class Group3DFrameMetrics:
    individual_count: int
    centroid_x: float
    centroid_y: float
    centroid_z: float
    mean_nearest_neighbor_distance: float
    mean_pairwise_distance: float
    bounding_box_volume: float


def scientific_depth_tier(
    *,
    metric_model: bool,
    camera_intrinsics_present: bool,
    physical_reference_validated: bool,
    stereo_geometry_validated: bool = False,
) -> ScientificDepthTier:
    if stereo_geometry_validated and camera_intrinsics_present and physical_reference_validated:
        return "stereo_metric"
    if metric_model and camera_intrinsics_present and physical_reference_validated:
        return "calibrated_metric"
    if metric_model:
        return "model_estimated_metric"
    return "relative_depth"


def allows_physical_measurement_claim(tier: ScientificDepthTier) -> bool:
    return tier in {"calibrated_metric", "stereo_metric"}


def _clip_bbox(
    bbox: Sequence[float],
    *,
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    if len(bbox) != 4:
        raise ValueError("bbox must contain x1, y1, x2, y2")
    x1, y1, x2, y2 = (float(value) for value in bbox)
    left = max(0, min(width - 1, int(np.floor(min(x1, x2)))))
    right = max(left + 1, min(width, int(np.ceil(max(x1, x2)))))
    top = max(0, min(height - 1, int(np.floor(min(y1, y2)))))
    bottom = max(top + 1, min(height, int(np.ceil(max(y1, y2)))))
    return left, top, right, bottom


def robust_track_depth(
    depth_frame: NDArray[Any],
    bbox: Sequence[float],
    *,
    core_fraction: float = 0.6,
    minimum_valid_fraction: float = 0.25,
) -> RobustDepthEstimate:
    depth = np.asarray(depth_frame, dtype=np.float32)
    if depth.ndim != 2:
        raise ValueError("depth_frame must be a 2D array")
    if not 0 < core_fraction <= 1:
        raise ValueError("core_fraction must be in (0, 1]")
    if not 0 <= minimum_valid_fraction <= 1:
        raise ValueError("minimum_valid_fraction must be in [0, 1]")

    height, width = depth.shape
    left, top, right, bottom = _clip_bbox(bbox, width=width, height=height)

    box_width = right - left
    box_height = bottom - top
    inset_x = round(box_width * (1 - core_fraction) / 2)
    inset_y = round(box_height * (1 - core_fraction) / 2)
    core_left = min(right - 1, left + inset_x)
    core_right = max(core_left + 1, right - inset_x)
    core_top = min(bottom - 1, top + inset_y)
    core_bottom = max(core_top + 1, bottom - inset_y)

    values = depth[core_top:core_bottom, core_left:core_right].reshape(-1)
    if values.size == 0:
        raise ValueError("track box contains no depth pixels")

    valid_mask = np.isfinite(values) & (values > 0)
    valid = values[valid_mask]
    valid_fraction = float(valid.size / values.size)
    if valid.size == 0 or valid_fraction < minimum_valid_fraction:
        raise ValueError("insufficient valid positive depth pixels inside the tracked fish")

    median = float(np.median(valid))
    mad = float(np.median(np.abs(valid - median)))
    robust_sigma = 1.4826 * mad
    relative_spread = robust_sigma / median if median > 0 else float("inf")
    confidence = valid_fraction * exp(-min(relative_spread, 10.0))
    confidence = max(0.0, min(1.0, confidence))

    return RobustDepthEstimate(
        depth=median,
        confidence=confidence,
        valid_fraction=valid_fraction,
        robust_relative_spread=relative_spread,
        sample_count=int(valid.size),
    )


def group_3d_frame_metrics(
    points: Sequence[Sequence[float]],
) -> Group3DFrameMetrics:
    xyz = np.asarray(points, dtype=np.float64)
    if xyz.ndim != 2 or xyz.shape[1] != 3:
        raise ValueError("points must have shape (n, 3)")
    if xyz.shape[0] < 2:
        raise ValueError("at least two XYZ positions are required")
    if not np.isfinite(xyz).all():
        raise ValueError("XYZ positions must be finite")

    centroid = xyz.mean(axis=0)
    deltas = xyz[:, None, :] - xyz[None, :, :]
    distances = np.linalg.norm(deltas, axis=2)
    upper = distances[np.triu_indices(xyz.shape[0], k=1)]
    nearest = np.where(
        np.eye(xyz.shape[0], dtype=bool),
        np.inf,
        distances,
    ).min(axis=1)
    spans = xyz.max(axis=0) - xyz.min(axis=0)

    return Group3DFrameMetrics(
        individual_count=int(xyz.shape[0]),
        centroid_x=float(centroid[0]),
        centroid_y=float(centroid[1]),
        centroid_z=float(centroid[2]),
        mean_nearest_neighbor_distance=float(nearest.mean()),
        mean_pairwise_distance=float(upper.mean()),
        bounding_box_volume=float(np.prod(spans)),
    )
