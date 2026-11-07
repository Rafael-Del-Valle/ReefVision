"""Gaussian heatmap targets for ReefPose training."""

from __future__ import annotations

from dataclasses import dataclass

import torch

from reefvision.ml.reefpose.errors import ReefPoseValidationError


@dataclass(slots=True)
class ReefPoseTargets:
    heatmaps: torch.Tensor
    heatmap_weights: torch.Tensor
    visibility_targets: torch.Tensor

    def batched(self) -> ReefPoseTargets:
        if self.heatmaps.ndim == 4:
            return self
        if self.heatmaps.ndim != 3:
            raise ReefPoseValidationError("ReefPose target heatmaps must be KHW or BKHW")
        return ReefPoseTargets(
            heatmaps=self.heatmaps.unsqueeze(0),
            heatmap_weights=self.heatmap_weights.unsqueeze(0),
            visibility_targets=self.visibility_targets.unsqueeze(0),
        )

    def to(self, device: torch.device | str) -> ReefPoseTargets:
        return ReefPoseTargets(
            heatmaps=self.heatmaps.to(device),
            heatmap_weights=self.heatmap_weights.to(device),
            visibility_targets=self.visibility_targets.to(device),
        )


def generate_gaussian_heatmaps(
    points: torch.Tensor,
    visibility: torch.Tensor,
    *,
    height: int,
    width: int,
    sigma: float,
) -> ReefPoseTargets:
    """Generate fractional Gaussian targets using 0/1/2 visibility semantics."""

    if points.ndim != 2 or points.shape[-1] != 2:
        raise ReefPoseValidationError("Target points must have shape [keypoints, 2]")
    if visibility.ndim != 1 or visibility.shape[0] != points.shape[0]:
        raise ReefPoseValidationError("Target visibility must match the landmark count")
    if min(height, width) < 1 or sigma <= 0:
        raise ReefPoseValidationError("Heatmap dimensions and sigma must be positive")
    if not torch.isfinite(points).all() or not torch.isfinite(visibility).all():
        raise ReefPoseValidationError("Target coordinates and visibility must be finite")

    states = visibility.to(dtype=torch.int64)
    if not torch.equal(states.to(dtype=visibility.dtype), visibility):
        raise ReefPoseValidationError("Visibility values must be integers 0, 1, or 2")
    if not torch.all((states >= 0) & (states <= 2)):
        raise ReefPoseValidationError("Visibility values must be 0, 1, or 2")

    point_values = points.to(dtype=torch.float32)
    supervised = states > 0
    outside = supervised & (
        (point_values[:, 0] < 0)
        | (point_values[:, 0] >= width)
        | (point_values[:, 1] < 0)
        | (point_values[:, 1] >= height)
    )
    if bool(outside.any()):
        raise ReefPoseValidationError("Visible target coordinates fall outside the heatmap")

    y_grid = torch.arange(height, device=points.device, dtype=torch.float32)
    x_grid = torch.arange(width, device=points.device, dtype=torch.float32)
    yy, xx = torch.meshgrid(y_grid, x_grid, indexing="ij")
    squared_distance = (xx.unsqueeze(0) - point_values[:, 0, None, None]).square() + (
        yy.unsqueeze(0) - point_values[:, 1, None, None]
    ).square()
    heatmaps = torch.exp(-squared_distance / (2.0 * float(sigma) ** 2))
    heatmaps *= supervised[:, None, None].to(dtype=heatmaps.dtype)
    heatmap_weights = torch.where(
        states == 2,
        torch.ones_like(states, dtype=torch.float32),
        torch.where(
            states == 1,
            torch.full_like(states, 0.5, dtype=torch.float32),
            torch.zeros_like(states, dtype=torch.float32),
        ),
    )
    return ReefPoseTargets(
        heatmaps=heatmaps,
        heatmap_weights=heatmap_weights,
        visibility_targets=supervised.to(dtype=torch.float32),
    )
