"""Depth Anything V2 inference adapter."""

from __future__ import annotations

from typing import Any

import numpy as np
from PIL import Image

from reefvision.ml.provider_contract import ProviderRequest, ProviderResult


class DepthAnythingV2Provider:
    """Run relative-depth estimation through the Transformers pipeline."""

    provider_id = "depth_anything_v2"
    supported_tasks = frozenset({"depth"})

    def preflight(self, request: ProviderRequest) -> list[str]:
        blockers: list[str] = []

        if request.source_path is None or not request.source_path.is_file():
            blockers.append("A readable image source is required.")

        try:
            import transformers  # noqa: F401
        except ImportError:
            blockers.append("Install the optional transformers dependency.")

        return blockers

    def train(self, request: ProviderRequest) -> ProviderResult:
        raise NotImplementedError("Depth Anything V2 is inference-only in ReefVision.")

    def infer(self, request: ProviderRequest) -> ProviderResult:
        blockers = self.preflight(request)
        if blockers:
            raise ValueError("; ".join(blockers))

        source_path = request.source_path
        if source_path is None:
            raise ValueError("A source image path is required.")

        from transformers import pipeline

        model_id = str(
            request.parameters.get(
                "model_id",
                "depth-anything/Depth-Anything-V2-Small-hf",
            )
        )
        device = int(request.parameters.get("device", 0))

        depth_pipeline = pipeline(
            "depth-estimation",
            model=model_id,
            device=device,
        )

        result: dict[str, Any] = depth_pipeline(Image.open(source_path).convert("RGB"))

        predicted_depth = result.get("predicted_depth")
        if predicted_depth is None:
            raise RuntimeError("Depth Anything V2 did not return predicted_depth.")

        depth = np.asarray(predicted_depth, dtype=np.float32)

        output_dir = request.output_dir or source_path.parent
        output_dir.mkdir(parents=True, exist_ok=True)

        depth_path = output_dir / f"{source_path.stem}.depth.npy"
        np.save(depth_path, depth)

        return ProviderResult(
            artifacts={"depth_npy": str(depth_path)},
            metadata={
                "provider": self.provider_id,
                "model_id": model_id,
                "depth_kind": "relative",
            },
        )
