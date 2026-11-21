"""Offline image descriptors from the explicitly registered native pose encoder."""

from pathlib import Path

import torch
from PIL import Image
from torch.nn import functional as F

from reefvision.ml.reefpose.checkpoints import load_checkpoint
from reefvision.ml.reefpose.errors import ReefPoseValidationError
from reefvision.ml.reefpose.geometry import letterbox_tensor
from reefvision.ml.reefpose.inference import ReefPosePredictor
from reefvision.ml.reefpose.training import resolve_device

METHOD = "reefpose-s-stages-2-4-rgb-mean-l2-cosine-v1"


class AppearanceEncoder:
    def __init__(self, path: Path, device: str) -> None:
        self.device = resolve_device(device)
        state = load_checkpoint(path, device=self.device)
        if state.global_step < 1:
            raise ReefPoseValidationError("Choose a trained native ReefPose checkpoint")
        self.model = state.model.to(self.device).eval()
        self.schema = state.schema
        self.global_step = state.global_step

    def encode(self, crop: Image.Image) -> list[float]:
        image, _ = letterbox_tensor(
            ReefPosePredictor._image_tensor(crop),
            input_height=self.model.config.input_height,
            input_width=self.model.config.input_width,
        )
        with torch.inference_mode():
            features = self.model.extract_features(image.unsqueeze(0).to(self.device))
            pools = [F.normalize(feature.mean(dim=(2, 3)), dim=1) for feature in features[1:]]
            joined = torch.cat(pools, dim=1)
            if not torch.isfinite(joined).all() or float(joined.norm()) <= 1e-12:
                raise ReefPoseValidationError("This crop has no finite appearance descriptor")
            values = F.normalize(joined, dim=1)[0].detach().cpu().tolist()
        return [float(value) for value in values]
