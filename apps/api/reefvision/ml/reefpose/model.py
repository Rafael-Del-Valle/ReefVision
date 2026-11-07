"""Native convolutional ReefPose-S architecture."""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import nn
from torch.nn import functional as F

from reefvision.ml.reefpose.errors import ReefPoseValidationError


@dataclass(frozen=True, slots=True)
class ReefPoseConfig:
    num_keypoints: int
    input_height: int = 256
    input_width: int = 256
    input_channels: int = 3
    base_channels: int = 32
    fpn_channels: int | None = None
    heatmap_stride: int = 4

    def __post_init__(self) -> None:
        if self.num_keypoints < 1:
            raise ReefPoseValidationError("ReefPose requires at least one keypoint")
        if self.input_channels < 1 or self.base_channels < 4:
            raise ReefPoseValidationError("ReefPose channel counts are invalid")
        if self.input_height % 32 or self.input_width % 32:
            raise ReefPoseValidationError("ReefPose input dimensions must be divisible by 32")
        if self.heatmap_stride != 4:
            raise ReefPoseValidationError("ReefPose-S currently requires heatmap stride 4")
        if self.fpn_channels is not None and self.fpn_channels < 4:
            raise ReefPoseValidationError("ReefPose FPN channels must be at least 4")

    @property
    def resolved_fpn_channels(self) -> int:
        return self.fpn_channels or self.base_channels * 4

    def to_dict(self) -> dict[str, int | None]:
        return {
            "num_keypoints": self.num_keypoints,
            "input_height": self.input_height,
            "input_width": self.input_width,
            "input_channels": self.input_channels,
            "base_channels": self.base_channels,
            "fpn_channels": self.fpn_channels,
            "heatmap_stride": self.heatmap_stride,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> ReefPoseConfig:
        return cls(
            num_keypoints=int(payload["num_keypoints"]),
            input_height=int(payload.get("input_height", 256)),
            input_width=int(payload.get("input_width", 256)),
            input_channels=int(payload.get("input_channels", 3)),
            base_channels=int(payload.get("base_channels", 32)),
            fpn_channels=(
                int(payload["fpn_channels"]) if payload.get("fpn_channels") is not None else None
            ),
            heatmap_stride=int(payload.get("heatmap_stride", 4)),
        )


@dataclass(slots=True)
class ReefPoseOutput:
    heatmaps: torch.Tensor
    visibility_logits: torch.Tensor


class ConvNormAct(nn.Sequential):
    def __init__(
        self,
        in_channels: int,
        out_channels: int,
        *,
        kernel_size: int = 3,
        stride: int = 1,
    ) -> None:
        padding = kernel_size // 2
        super().__init__(
            nn.Conv2d(
                in_channels,
                out_channels,
                kernel_size,
                stride=stride,
                padding=padding,
                bias=False,
            ),
            nn.BatchNorm2d(out_channels),
            nn.SiLU(inplace=True),
        )


class ResidualBlock(nn.Module):
    def __init__(self, channels: int) -> None:
        super().__init__()
        self.block = nn.Sequential(
            ConvNormAct(channels, channels),
            nn.Conv2d(channels, channels, 3, padding=1, bias=False),
            nn.BatchNorm2d(channels),
        )
        self.activation = nn.SiLU(inplace=True)

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        return self.activation(inputs + self.block(inputs))


class EncoderStage(nn.Sequential):
    def __init__(self, in_channels: int, out_channels: int) -> None:
        super().__init__(
            ConvNormAct(in_channels, out_channels, stride=2),
            ResidualBlock(out_channels),
        )


class ReefPoseS(nn.Module):
    """Small native CNN with a top-down multi-scale feature pyramid."""

    architecture_name = "reefpose-s"
    architecture_version = "1"

    def __init__(self, config: ReefPoseConfig) -> None:
        super().__init__()
        self.config = config
        base = config.base_channels
        self.stem = ConvNormAct(config.input_channels, base, stride=2)
        self.stage1 = EncoderStage(base, base)
        self.stage2 = EncoderStage(base, base * 2)
        self.stage3 = EncoderStage(base * 2, base * 4)
        self.stage4 = EncoderStage(base * 4, base * 8)

        pyramid = config.resolved_fpn_channels
        self.lateral = nn.ModuleList(
            [
                nn.Conv2d(base, pyramid, 1),
                nn.Conv2d(base * 2, pyramid, 1),
                nn.Conv2d(base * 4, pyramid, 1),
                nn.Conv2d(base * 8, pyramid, 1),
            ]
        )
        self.refine = nn.ModuleList([ConvNormAct(pyramid, pyramid) for _ in range(3)])
        self.heatmap_head = nn.Sequential(
            ConvNormAct(pyramid, pyramid),
            nn.Conv2d(pyramid, config.num_keypoints, 1),
        )
        self.visibility_head = nn.Sequential(
            nn.AdaptiveAvgPool2d(1),
            nn.Flatten(),
            nn.Linear(base * 8, config.num_keypoints),
        )
        self._initialize_weights()

    def _initialize_weights(self) -> None:
        for module in self.modules():
            if isinstance(module, nn.Conv2d):
                nn.init.kaiming_normal_(module.weight, mode="fan_out", nonlinearity="relu")
            elif isinstance(module, nn.BatchNorm2d):
                nn.init.ones_(module.weight)
                nn.init.zeros_(module.bias)
            elif isinstance(module, nn.Linear):
                nn.init.normal_(module.weight, std=0.01)
                nn.init.zeros_(module.bias)
        final = self.heatmap_head[-1]
        if isinstance(final, nn.Conv2d) and final.bias is not None:
            nn.init.constant_(final.bias, -2.19)

    def extract_features(self, inputs: torch.Tensor) -> tuple[torch.Tensor, ...]:
        self._validate_inputs(inputs)
        stem = self.stem(inputs)
        feature1 = self.stage1(stem)
        feature2 = self.stage2(feature1)
        feature3 = self.stage3(feature2)
        feature4 = self.stage4(feature3)
        return feature1, feature2, feature3, feature4

    def forward(self, inputs: torch.Tensor) -> ReefPoseOutput:
        features = self.extract_features(inputs)
        pyramid = self.lateral[-1](features[-1])
        for index in range(2, -1, -1):
            pyramid = F.interpolate(
                pyramid,
                size=features[index].shape[-2:],
                mode="bilinear",
                align_corners=False,
            )
            pyramid = self.refine[index](pyramid + self.lateral[index](features[index]))
        return ReefPoseOutput(
            heatmaps=self.heatmap_head(pyramid),
            visibility_logits=self.visibility_head(features[-1]),
        )

    def _validate_inputs(self, inputs: torch.Tensor) -> None:
        expected = (
            self.config.input_channels,
            self.config.input_height,
            self.config.input_width,
        )
        if inputs.ndim != 4 or tuple(inputs.shape[1:]) != expected:
            raise ReefPoseValidationError(
                "ReefPose input must have shape "
                f"[batch, {expected[0]}, {expected[1]}, {expected[2]}]"
            )

