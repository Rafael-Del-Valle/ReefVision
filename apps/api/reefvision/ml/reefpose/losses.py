"""Visibility-aware objectives for ReefPose heatmaps."""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import nn
from torch.nn import functional as F

from reefvision.ml.reefpose.errors import ReefPoseValidationError
from reefvision.ml.reefpose.model import ReefPoseOutput
from reefvision.ml.reefpose.targets import ReefPoseTargets


@dataclass(slots=True)
class ReefPoseLossOutput:
    total: torch.Tensor
    heatmap: torch.Tensor
    visibility: torch.Tensor


class ReefPoseLoss(nn.Module):
    def __init__(
        self,
        *,
        heatmap_loss_weight: float = 1.0,
        visibility_loss_weight: float = 0.1,
    ) -> None:
        super().__init__()
        if heatmap_loss_weight < 0 or visibility_loss_weight < 0:
            raise ReefPoseValidationError("ReefPose loss weights cannot be negative")
        if heatmap_loss_weight + visibility_loss_weight <= 0:
            raise ReefPoseValidationError("At least one ReefPose loss must be enabled")
        self.heatmap_loss_weight = float(heatmap_loss_weight)
        self.visibility_loss_weight = float(visibility_loss_weight)

    def forward(
        self,
        prediction: ReefPoseOutput,
        targets: ReefPoseTargets,
    ) -> ReefPoseLossOutput:
        target_batch = targets.batched()
        if prediction.heatmaps.shape != target_batch.heatmaps.shape:
            raise ReefPoseValidationError("Predicted and target heatmap shapes must match")
        if prediction.visibility_logits.shape != target_batch.visibility_targets.shape:
            raise ReefPoseValidationError("Predicted and target visibility shapes must match")
        if target_batch.heatmap_weights.shape != prediction.visibility_logits.shape:
            raise ReefPoseValidationError("Heatmap weights must match the landmark batch")

        squared_error = (torch.sigmoid(prediction.heatmaps) - target_batch.heatmaps).square()
        weights = target_batch.heatmap_weights[:, :, None, None]
        height, width = prediction.heatmaps.shape[-2:]
        denominator = (target_batch.heatmap_weights.sum() * height * width).clamp_min(1.0)
        heatmap_loss = (squared_error * weights).sum() / denominator
        visibility_loss = F.binary_cross_entropy_with_logits(
            prediction.visibility_logits,
            target_batch.visibility_targets,
        )
        total = (
            heatmap_loss * self.heatmap_loss_weight
            + visibility_loss * self.visibility_loss_weight
        )
        return ReefPoseLossOutput(
            total=total,
            heatmap=heatmap_loss,
            visibility=visibility_loss,
        )

