"""Source-coordinate ReefPose inference."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image, UnidentifiedImageError
from torch import nn

from reefvision.ml.reefpose.checkpoints import load_checkpoint
from reefvision.ml.reefpose.errors import ReefPoseValidationError
from reefvision.ml.reefpose.geometry import letterbox_tensor
from reefvision.ml.reefpose.model import ReefPoseConfig, ReefPoseOutput
from reefvision.ml.reefpose.schema import AnatomySchema
from reefvision.ml.reefpose.training import resolve_device


@dataclass(frozen=True, slots=True)
class LandmarkPrediction:
    landmark_id: str
    name: str
    occurrence_index: int
    x: float
    y: float
    confidence: float
    heatmap_confidence: float
    visibility_probability: float
    visibility_state: str


@dataclass(frozen=True, slots=True)
class PosePrediction:
    landmarks: tuple[LandmarkPrediction, ...]
    confidence: float
    bbox: tuple[float, float, float, float] | None
    anatomy_schema_id: str
    anatomy_schema_revision: int
    anatomy_integrity_hash: str


class ReefPosePredictor:
    def __init__(
        self,
        model: nn.Module,
        schema: AnatomySchema,
        *,
        device: str = "auto",
    ) -> None:
        config = getattr(model, "config", None)
        if not isinstance(config, ReefPoseConfig):
            raise ReefPoseValidationError("ReefPose inference model lacks a valid configuration")
        if config.num_keypoints != schema.keypoint_count:
            raise ReefPoseValidationError("ReefPose model and anatomy landmark counts differ")
        self.model = model
        self.schema = schema
        self.config = config
        self.device = resolve_device(device)
        self.model.to(self.device)
        self.model.eval()

    @classmethod
    def from_checkpoint(
        cls,
        path: Path,
        *,
        device: str = "auto",
    ) -> ReefPosePredictor:
        resolved_device = resolve_device(device)
        state = load_checkpoint(path, device=resolved_device)
        return cls(state.model, state.schema, device=str(resolved_device))

    @staticmethod
    def _image_tensor(source: Image.Image | Path | torch.Tensor) -> torch.Tensor:
        if isinstance(source, torch.Tensor):
            if source.ndim != 3 or source.shape[0] != 3:
                raise ReefPoseValidationError("Inference tensors must have shape [3,H,W]")
            tensor = source.detach().to(dtype=torch.float32, device="cpu")
            if float(tensor.max()) > 1.0:
                tensor = tensor / 255.0
            return tensor
        try:
            if isinstance(source, Path):
                with Image.open(source) as opened:
                    image = opened.convert("RGB")
                    array = np.array(image, dtype=np.uint8, copy=True)
            else:
                array = np.array(source.convert("RGB"), dtype=np.uint8, copy=True)
        except (OSError, UnidentifiedImageError) as exc:
            raise ReefPoseValidationError("Inference source is not a readable image") from exc
        return torch.from_numpy(array).permute(2, 0, 1).float().div_(255.0)

    @staticmethod
    def _bbox(
        landmarks: list[LandmarkPrediction], source_width: int, source_height: int
    ) -> tuple[float, float, float, float] | None:
        visible = [item for item in landmarks if item.visibility_state == "visible"]
        if not visible:
            return None
        x_min = max(0.0, min(item.x for item in visible) - 1.0)
        y_min = max(0.0, min(item.y for item in visible) - 1.0)
        x_max = min(float(source_width), max(item.x for item in visible) + 1.0)
        y_max = min(float(source_height), max(item.y for item in visible) + 1.0)
        if x_max <= x_min:
            x_max = min(float(source_width), x_min + 1.0)
        if y_max <= y_min:
            y_max = min(float(source_height), y_min + 1.0)
        return x_min, y_min, x_max, y_max

    def predict(
        self,
        source: Image.Image | Path | torch.Tensor,
        *,
        crop_box: tuple[int, int, int, int] | None = None,
        confidence_threshold: float = 0.0,
    ) -> PosePrediction:
        if not 0 <= confidence_threshold <= 1:
            raise ReefPoseValidationError("Inference confidence threshold must be 0 to 1")
        source_tensor = self._image_tensor(source)
        source_height, source_width = source_tensor.shape[-2:]
        network_image, transform = letterbox_tensor(
            source_tensor,
            input_height=self.config.input_height,
            input_width=self.config.input_width,
            crop_box=crop_box,
        )
        with torch.inference_mode():
            output = self.model(network_image.unsqueeze(0).to(self.device))
        if not isinstance(output, ReefPoseOutput):
            raise ReefPoseValidationError("ReefPose model returned an invalid output")
        heatmaps = torch.sigmoid(output.heatmaps[0]).detach().cpu()
        visibility = torch.sigmoid(output.visibility_logits[0]).detach().cpu()
        if heatmaps.shape[0] != self.schema.keypoint_count:
            raise ReefPoseValidationError("ReefPose output landmark count is invalid")
        heatmap_height, heatmap_width = heatmaps.shape[-2:]
        landmark_predictions: list[LandmarkPrediction] = []
        for index, landmark in enumerate(self.schema.landmarks):
            flat_index = int(heatmaps[index].reshape(-1).argmax())
            heatmap_y, heatmap_x = divmod(flat_index, heatmap_width)
            heatmap_confidence = float(heatmaps[index, heatmap_y, heatmap_x])
            visibility_probability = float(visibility[index])
            confidence = max(0.0, min(1.0, heatmap_confidence * visibility_probability))
            source_point = transform.heatmap_to_source(
                torch.tensor([[float(heatmap_x), float(heatmap_y)]]),
                heatmap_width,
                heatmap_height,
                clamp=True,
            )[0]
            is_visible = visibility_probability >= 0.5 and confidence >= confidence_threshold
            x = float(source_point[0]) if is_visible else 0.0
            y = float(source_point[1]) if is_visible else 0.0
            if not math.isfinite(x) or not math.isfinite(y):
                raise ReefPoseValidationError("ReefPose decoded a non-finite coordinate")
            landmark_predictions.append(
                LandmarkPrediction(
                    landmark_id=landmark.landmark_id,
                    name=landmark.name,
                    occurrence_index=landmark.occurrence_index,
                    x=x,
                    y=y,
                    confidence=confidence,
                    heatmap_confidence=heatmap_confidence,
                    visibility_probability=visibility_probability,
                    visibility_state="visible" if is_visible else "absent",
                )
            )
        overall_confidence = sum(item.confidence for item in landmark_predictions) / len(
            landmark_predictions
        )
        return PosePrediction(
            landmarks=tuple(landmark_predictions),
            confidence=overall_confidence,
            bbox=self._bbox(landmark_predictions, source_width, source_height),
            anatomy_schema_id=self.schema.schema_id,
            anatomy_schema_revision=self.schema.revision,
            anatomy_integrity_hash=self.schema.integrity_hash,
        )

