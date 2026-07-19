"""Optional image-depth providers with no implicit model downloads."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from reefvision.domain.errors import ValidationError


def luminance_relative_depth(image: Image.Image) -> np.ndarray:
    """Produce a deterministic relative-depth fixture from image luminance.

    This provider is intended for workflow testing and previews, not scientific depth.
    Brighter pixels receive lower normalized values and darker pixels higher values.
    """

    gray = np.asarray(image.convert("L"), dtype=np.float32) / 255.0
    depth = 1.0 - gray
    low = float(np.min(depth))
    high = float(np.max(depth))
    if high > low:
        depth = (depth - low) / (high - low)
    return depth.astype(np.float32)


def _device_name(requested: str) -> str:
    normalized = requested.strip().casefold()
    if normalized in {"", "auto"}:
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            return "cpu"
    return requested


def depth_anything_v2(
    image: Image.Image,
    *,
    model_id: str,
    device: str,
    local_files_only: bool,
    metric: bool,
    maximum_metric_depth: float | None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Run a local Hugging Face Depth Anything V2-compatible checkpoint."""

    try:
        import torch
        import torch.nn.functional as functional
        from transformers import AutoImageProcessor, AutoModelForDepthEstimation
    except ImportError as exc:
        raise ValidationError(
            "Depth Anything V2 requires the optional torch and transformers dependencies"
        ) from exc

    resolved_device = _device_name(device)
    try:
        processor = AutoImageProcessor.from_pretrained(
            model_id,
            local_files_only=local_files_only,
        )
        model = AutoModelForDepthEstimation.from_pretrained(
            model_id,
            local_files_only=local_files_only,
        )
    except Exception as exc:
        download_note = (
            " Install or import the checkpoint locally before generation."
            if local_files_only
            else " Check the model identifier and network access."
        )
        raise ValidationError(f"Depth checkpoint could not be loaded.{download_note}") from exc

    model.to(resolved_device)
    model.eval()
    inputs = processor(images=image.convert("RGB"), return_tensors="pt")
    inputs = {key: value.to(resolved_device) for key, value in inputs.items()}
    with torch.inference_mode():
        outputs = model(**inputs)
        predicted = outputs.predicted_depth
        resized = functional.interpolate(
            predicted.unsqueeze(1),
            size=(image.height, image.width),
            mode="bicubic",
            align_corners=False,
        ).squeeze(0).squeeze(0)
    values = resized.detach().float().cpu().numpy().astype(np.float32)
    if metric:
        if maximum_metric_depth is not None:
            values = np.clip(values, 0, float(maximum_metric_depth))
        positive = values[np.isfinite(values) & (values > 0)]
        if positive.size == 0:
            raise ValidationError("The metric depth checkpoint produced no positive depths")
    else:
        finite = np.isfinite(values)
        observed = values[finite]
        low, high = float(np.min(observed)), float(np.max(observed))
        if high > low:
            values[finite] = (values[finite] - low) / (high - low)
    metadata = {
        "runtime": "transformers.AutoModelForDepthEstimation",
        "resolved_device": resolved_device,
        "model_id": model_id,
        "local_files_only": local_files_only,
        "metric_requested": metric,
        "maximum_metric_depth": maximum_metric_depth,
    }
    return values, metadata


def generate_depth_map(
    image_path: Path,
    *,
    provider_id: str,
    model_id: str,
    device: str,
    local_files_only: bool,
    maximum_metric_depth: float | None,
) -> tuple[np.ndarray, dict[str, Any]]:
    if not image_path.is_file():
        raise ValidationError("The managed source image is missing")
    with Image.open(image_path) as source:
        source.load()
        image = source.convert("RGB")
    if provider_id == "luminance_relative":
        return luminance_relative_depth(image), {
            "runtime": "reefvision.luminance_relative_depth",
            "scientific_use": False,
            "warning": (
                "Luminance depth is a deterministic workflow fixture and must not be "
                "interpreted as physical scene depth."
            ),
        }
    if provider_id == "depth_anything_v2_relative":
        return depth_anything_v2(
            image,
            model_id=model_id,
            device=device,
            local_files_only=local_files_only,
            metric=False,
            maximum_metric_depth=None,
        )
    if provider_id == "depth_anything_v2_metric":
        return depth_anything_v2(
            image,
            model_id=model_id,
            device=device,
            local_files_only=local_files_only,
            metric=True,
            maximum_metric_depth=maximum_metric_depth,
        )
    raise ValidationError("Unsupported depth provider")
