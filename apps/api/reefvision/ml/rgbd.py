"""Reusable RGB-D fusion primitives for future depth-aware model providers."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any, cast

import numpy as np
from numpy.typing import NDArray

from reefvision.domain.errors import ValidationError


def normalize_depth(
    depth: NDArray[Any],
    *,
    mode: str = "per_image",
    dataset_mean: float | None = None,
    dataset_std: float | None = None,
) -> NDArray[Any]:
    """Normalize an aligned depth plane while preserving invalid-pixel masking."""

    values = np.asarray(depth, dtype=np.float32)
    if values.ndim != 2:
        raise ValidationError("RGB-D depth input must be a two-dimensional plane")
    finite = np.isfinite(values)
    if not finite.any():
        raise ValidationError("RGB-D depth input contains no finite values")
    result = np.zeros_like(values, dtype=np.float32)
    observed = values[finite]
    if mode == "none" or mode == "metric":
        result[finite] = observed
    elif mode == "per_image":
        median = float(np.median(observed))
        low = float(np.percentile(observed, 2))
        high = float(np.percentile(observed, 98))
        scale = max(high - low, 1e-6)
        result[finite] = np.clip((observed - median) / scale, -2.0, 2.0)
    elif mode == "dataset":
        if dataset_mean is None or dataset_std is None or dataset_std <= 0:
            raise ValidationError(
                "Dataset depth normalization requires a finite mean and positive standard deviation"
            )
        result[finite] = (observed - float(dataset_mean)) / float(dataset_std)
    else:
        raise ValidationError("Unknown RGB-D depth normalization mode")
    return result


def stack_rgbd(
    rgb: NDArray[Any],
    depth: NDArray[Any],
    *,
    depth_normalization: str = "per_image",
    dataset_mean: float | None = None,
    dataset_std: float | None = None,
) -> NDArray[Any]:
    """Create an HxWx4 RGB-D array with an explicitly normalized depth channel."""

    image = np.asarray(rgb)
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValidationError("RGB-D fusion requires an HxWx3 RGB image")
    if image.shape[:2] != np.asarray(depth).shape:
        raise ValidationError("RGB and depth dimensions must match exactly")
    rgb_float = image.astype(np.float32)
    if np.issubdtype(image.dtype, np.integer):
        rgb_float /= float(np.iinfo(image.dtype).max)
    normalized = normalize_depth(
        depth,
        mode=depth_normalization,
        dataset_mean=dataset_mean,
        dataset_std=dataset_std,
    )
    return np.concatenate((rgb_float, normalized[..., None]), axis=2)


def adapt_first_convolution_to_rgbd(
    convolution: Any,
    *,
    depth_weight_scale: float = 1.0,
) -> Any:
    """Replace a three-channel torch Conv2d with a four-channel RGB-D layer.

    RGB weights are copied exactly. The new depth-channel weights are initialized
    from the mean RGB kernel, which preserves pretrained behavior better than a
    random fourth channel while still requiring subsequent RGB-D fine-tuning.
    """

    try:
        import torch
        from torch import nn
    except ImportError as exc:
        raise ValidationError("RGB-D convolution adaptation requires PyTorch") from exc
    if not isinstance(convolution, nn.Conv2d):
        raise ValidationError("The selected layer is not a PyTorch Conv2d")
    if convolution.in_channels != 3:
        raise ValidationError("Only three-channel input convolutions can be adapted to RGB-D")
    if convolution.groups != 1:
        raise ValidationError(
            "Grouped first convolutions require a provider-specific RGB-D adapter"
        )
    replacement = nn.Conv2d(
        in_channels=4,
        out_channels=convolution.out_channels,
        kernel_size=cast(tuple[int, int], convolution.kernel_size),
        stride=cast(tuple[int, int], convolution.stride),
        padding=cast(
            str | int | tuple[int, int],
            convolution.padding,
        ),
        dilation=cast(tuple[int, int], convolution.dilation),
        groups=convolution.groups,
        bias=convolution.bias is not None,
        padding_mode=convolution.padding_mode,
        device=convolution.weight.device,
        dtype=convolution.weight.dtype,
    )
    with torch.no_grad():
        replacement.weight[:, :3].copy_(convolution.weight)
        replacement.weight[:, 3:4].copy_(
            convolution.weight.mean(dim=1, keepdim=True) * float(depth_weight_scale)
        )
        if convolution.bias is not None and replacement.bias is not None:
            replacement.bias.copy_(convolution.bias)
    return replacement


def depth_aware_association_cost(
    *,
    appearance_cost: float,
    motion_cost: float,
    detection_depth: float | None,
    track_depth_history: Sequence[float],
    appearance_weight: float = 0.5,
    motion_weight: float = 0.3,
    depth_weight: float = 0.2,
    depth_scale: float | None = None,
    maximum_normalized_depth_gap: float | None = None,
) -> tuple[float, bool, dict[str, float | None]]:
    """Blend depth with appearance/motion association and optionally gate matches."""

    weights = (appearance_weight, motion_weight, depth_weight)
    if any(weight < 0 or not math.isfinite(weight) for weight in weights):
        raise ValidationError("Association weights must be finite and non-negative")
    total_weight = sum(weights)
    if total_weight <= 0:
        raise ValidationError("At least one association weight must be positive")
    history = [float(value) for value in track_depth_history if math.isfinite(float(value))]
    track_depth = float(np.median(history)) if history else None
    normalized_gap = None
    if detection_depth is not None and track_depth is not None:
        scale = (
            float(depth_scale)
            if depth_scale is not None and depth_scale > 0
            else max(abs(track_depth), abs(float(detection_depth)), 1e-6)
        )
        normalized_gap = abs(float(detection_depth) - track_depth) / scale
    effective_depth_weight = depth_weight if normalized_gap is not None else 0.0
    effective_total = appearance_weight + motion_weight + effective_depth_weight
    cost = (
        appearance_weight * float(appearance_cost)
        + motion_weight * float(motion_cost)
        + effective_depth_weight * float(normalized_gap or 0.0)
    ) / max(effective_total, 1e-12)
    gated = bool(
        normalized_gap is not None
        and maximum_normalized_depth_gap is not None
        and normalized_gap > maximum_normalized_depth_gap
    )
    return (
        cost,
        gated,
        {
            "track_depth": track_depth,
            "detection_depth": detection_depth,
            "normalized_depth_gap": normalized_gap,
        },
    )
