"""Recorded image geometry for exact ReefPose coordinate restoration."""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch.nn import functional as F

from reefvision.ml.reefpose.errors import ReefPoseValidationError


@dataclass(frozen=True, slots=True)
class ImageTransform:
    """Aspect-preserving source/crop-to-network transform."""

    source_width: int
    source_height: int
    input_width: int
    input_height: int
    crop_x: float
    crop_y: float
    crop_width: float
    crop_height: float
    resized_width: int
    resized_height: int
    pad_left: int
    pad_top: int
    pad_right: int
    pad_bottom: int

    @classmethod
    def for_source(
        cls,
        *,
        source_width: int,
        source_height: int,
        input_width: int,
        input_height: int,
        crop_box: tuple[float, float, float, float] | None = None,
    ) -> ImageTransform:
        if min(source_width, source_height, input_width, input_height) < 1:
            raise ReefPoseValidationError("Image dimensions must be positive")
        if crop_box is None:
            crop_x, crop_y = 0.0, 0.0
            crop_x_max, crop_y_max = float(source_width), float(source_height)
        else:
            crop_x, crop_y, crop_x_max, crop_y_max = (float(item) for item in crop_box)
            if (
                crop_x < 0
                or crop_y < 0
                or crop_x_max > source_width
                or crop_y_max > source_height
                or crop_x_max <= crop_x
                or crop_y_max <= crop_y
            ):
                raise ReefPoseValidationError("Crop box must have positive area inside the source")
        crop_width = crop_x_max - crop_x
        crop_height = crop_y_max - crop_y
        scale = min(input_width / crop_width, input_height / crop_height)
        resized_width = min(input_width, max(1, round(crop_width * scale)))
        resized_height = min(input_height, max(1, round(crop_height * scale)))
        horizontal_padding = input_width - resized_width
        vertical_padding = input_height - resized_height
        pad_left = horizontal_padding // 2
        pad_top = vertical_padding // 2
        return cls(
            source_width=source_width,
            source_height=source_height,
            input_width=input_width,
            input_height=input_height,
            crop_x=crop_x,
            crop_y=crop_y,
            crop_width=crop_width,
            crop_height=crop_height,
            resized_width=resized_width,
            resized_height=resized_height,
            pad_left=pad_left,
            pad_top=pad_top,
            pad_right=horizontal_padding - pad_left,
            pad_bottom=vertical_padding - pad_top,
        )

    def source_to_input(self, points: torch.Tensor) -> torch.Tensor:
        self._validate_points(points)
        output = points.to(dtype=torch.float32).clone()
        output[..., 0] = (
            (output[..., 0] - self.crop_x) * self.resized_width / self.crop_width
            + self.pad_left
        )
        output[..., 1] = (
            (output[..., 1] - self.crop_y) * self.resized_height / self.crop_height
            + self.pad_top
        )
        return output

    def input_to_source(self, points: torch.Tensor, *, clamp: bool = False) -> torch.Tensor:
        self._validate_points(points)
        output = points.to(dtype=torch.float32).clone()
        output[..., 0] = (
            (output[..., 0] - self.pad_left) * self.crop_width / self.resized_width
            + self.crop_x
        )
        output[..., 1] = (
            (output[..., 1] - self.pad_top) * self.crop_height / self.resized_height
            + self.crop_y
        )
        if clamp:
            output[..., 0].clamp_(0.0, float(self.source_width - 1))
            output[..., 1].clamp_(0.0, float(self.source_height - 1))
        return output

    def source_to_heatmap(
        self, points: torch.Tensor, heatmap_width: int, heatmap_height: int
    ) -> torch.Tensor:
        if min(heatmap_width, heatmap_height) < 1:
            raise ReefPoseValidationError("Heatmap dimensions must be positive")
        output = self.source_to_input(points)
        output[..., 0] *= heatmap_width / self.input_width
        output[..., 1] *= heatmap_height / self.input_height
        return output

    def heatmap_to_source(
        self,
        points: torch.Tensor,
        heatmap_width: int,
        heatmap_height: int,
        *,
        clamp: bool = False,
    ) -> torch.Tensor:
        if min(heatmap_width, heatmap_height) < 1:
            raise ReefPoseValidationError("Heatmap dimensions must be positive")
        input_points = points.to(dtype=torch.float32).clone()
        input_points[..., 0] *= self.input_width / heatmap_width
        input_points[..., 1] *= self.input_height / heatmap_height
        return self.input_to_source(input_points, clamp=clamp)

    @staticmethod
    def _validate_points(points: torch.Tensor) -> None:
        if points.ndim < 1 or points.shape[-1] != 2:
            raise ReefPoseValidationError("Coordinate tensors must end with an x,y dimension")
        if not torch.isfinite(points).all():
            raise ReefPoseValidationError("Coordinates must be finite")


def letterbox_tensor(
    image: torch.Tensor,
    *,
    input_height: int,
    input_width: int,
    crop_box: tuple[int, int, int, int] | None = None,
    padding_value: float = 0.0,
) -> tuple[torch.Tensor, ImageTransform]:
    """Resize and pad a CHW tensor while returning its exact inverse transform."""

    if image.ndim != 3:
        raise ReefPoseValidationError("ReefPose images must be CHW tensors")
    _, source_height, source_width = image.shape
    transform = ImageTransform.for_source(
        source_width=source_width,
        source_height=source_height,
        input_width=input_width,
        input_height=input_height,
        crop_box=tuple(float(item) for item in crop_box) if crop_box is not None else None,
    )
    working = image
    if crop_box is not None:
        x_min, y_min, x_max, y_max = crop_box
        working = working[:, y_min:y_max, x_min:x_max]
    resized = F.interpolate(
        working.unsqueeze(0).to(dtype=torch.float32),
        size=(transform.resized_height, transform.resized_width),
        mode="bilinear",
        align_corners=False,
    ).squeeze(0)
    padded = F.pad(
        resized,
        (transform.pad_left, transform.pad_right, transform.pad_top, transform.pad_bottom),
        value=float(padding_value),
    )
    return padded, transform

