"""Optional image-depth providers with no implicit model downloads."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from reefvision.domain.errors import ValidationError


def luminance_relative_depth(image: Image.Image) -> NDArray[Any]:
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
) -> tuple[NDArray[Any], dict[str, Any]]:
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
        processor = AutoImageProcessor.from_pretrained(  # type: ignore[no-untyped-call]
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

    config = getattr(model, "config", None)
    to_dict = getattr(config, "to_dict", None)
    if not callable(to_dict):
        raise ValidationError("The loaded checkpoint does not expose a readable model config")
    config_payload = to_dict()
    if not isinstance(config_payload, dict):
        raise ValidationError("The loaded checkpoint returned an invalid model config")
    compatible, compatibility_reason, checkpoint_max_depth = _depth_checkpoint_config_status(
        config_payload,
        metric_required=metric,
    )
    if not compatible:
        raise ValidationError(
            compatibility_reason or "The loaded checkpoint is incompatible with Depth Anything V2"
        )

    model.to(resolved_device)
    model.eval()
    inputs = processor(images=image.convert("RGB"), return_tensors="pt")
    inputs = {key: value.to(resolved_device) for key, value in inputs.items()}
    with torch.inference_mode():
        outputs = model(**inputs)
        predicted = outputs.predicted_depth
        resized = (
            functional.interpolate(
                predicted.unsqueeze(1),
                size=(image.height, image.width),
                mode="bicubic",
                align_corners=False,
            )
            .squeeze(0)
            .squeeze(0)
        )
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
        "checkpoint_depth_estimation_type": config_payload.get("depth_estimation_type"),
        "checkpoint_max_depth": checkpoint_max_depth,
    }
    return values, metadata


_WINDOWS_DRIVE_PATH = re.compile(r"^[A-Za-z]:[\\/]")


def _looks_like_local_model_path(model_id: str) -> bool:
    value = model_id.strip()
    return (
        value.startswith(("./", "../", ".\\", "..\\", "~"))
        or bool(_WINDOWS_DRIVE_PATH.match(value))
        or Path(value).expanduser().is_absolute()
    )


def _depth_checkpoint_config_status(
    config: dict[str, Any],
    *,
    metric_required: bool,
) -> tuple[bool, str | None, float | None]:
    if config.get("model_type") != "depth_anything":
        return False, "The checkpoint config is not a Depth Anything model.", None

    raw_max_depth = config.get("max_depth")
    checkpoint_max_depth = (
        float(raw_max_depth)
        if isinstance(raw_max_depth, (int, float))
        and not isinstance(raw_max_depth, bool)
        and float(raw_max_depth) > 0
        else None
    )
    if metric_required:
        if config.get("depth_estimation_type") != "metric":
            return (
                False,
                "The metric provider requires a metric Depth Anything checkpoint.",
                checkpoint_max_depth,
            )
        if checkpoint_max_depth is None:
            return (
                False,
                "The metric checkpoint config must define a positive max_depth.",
                None,
            )
    return True, None, checkpoint_max_depth


def _local_depth_checkpoint_status(
    path: Path,
    *,
    metric_required: bool,
) -> tuple[bool, str | None]:
    if not path.exists():
        return False, "The selected local Depth Anything checkpoint does not exist."
    if not path.is_dir():
        return False, "A local Hugging Face Depth Anything checkpoint must be a directory."

    config_path = path / "config.json"
    if not config_path.is_file():
        return False, "The local checkpoint directory is missing config.json."
    processor_path = path / "preprocessor_config.json"
    if not processor_path.is_file():
        return False, "The local checkpoint directory is missing preprocessor_config.json."
    try:
        config_payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, "The local checkpoint config.json could not be read."
    if not isinstance(config_payload, dict):
        return False, "The local checkpoint config.json must contain a JSON object."

    compatible, reason, _ = _depth_checkpoint_config_status(
        config_payload,
        metric_required=metric_required,
    )
    if not compatible:
        return False, reason

    weights = [
        *path.glob("*.safetensors"),
        *path.glob("*.bin"),
        *path.glob("*.safetensors.index.json"),
        *path.glob("*.bin.index.json"),
    ]
    if not any(candidate.is_file() for candidate in weights):
        return False, "The local checkpoint directory contains no model weights."
    return True, None


def inspect_depth_provider_readiness(
    *,
    provider_id: str,
    model_id: str,
    device: str,
    local_files_only: bool,
) -> dict[str, Any]:
    if provider_id == "luminance_relative":
        return {
            "provider_id": provider_id,
            "model_id": model_id,
            "ready": True,
            "resolved_device": "cpu",
            "model_source": "fixture",
            "requires_network": False,
            "reason": None,
            "dependencies": {},
        }
    if provider_id not in {"depth_anything_v2_relative", "depth_anything_v2_metric"}:
        return {
            "provider_id": provider_id,
            "model_id": model_id,
            "ready": False,
            "resolved_device": device,
            "model_source": "invalid",
            "requires_network": False,
            "reason": "Unsupported depth provider.",
            "dependencies": {},
        }

    dependencies = {
        "torch": importlib.util.find_spec("torch") is not None,
        "transformers": importlib.util.find_spec("transformers") is not None,
        "huggingface_hub": importlib.util.find_spec("huggingface_hub") is not None,
    }
    missing = [name for name, installed in dependencies.items() if not installed]
    if missing:
        return {
            "provider_id": provider_id,
            "model_id": model_id,
            "ready": False,
            "resolved_device": device,
            "model_source": "invalid",
            "requires_network": False,
            "reason": "Missing Depth Anything dependencies: " + ", ".join(missing),
            "dependencies": dependencies,
        }

    resolved_device = _device_name(device)
    if resolved_device.startswith("cuda"):
        import torch

        if not torch.cuda.is_available():
            return {
                "provider_id": provider_id,
                "model_id": model_id,
                "ready": False,
                "resolved_device": resolved_device,
                "model_source": "invalid",
                "requires_network": False,
                "reason": "CUDA was requested, but PyTorch cannot access a CUDA device.",
                "dependencies": dependencies,
            }
    elif resolved_device != "cpu":
        return {
            "provider_id": provider_id,
            "model_id": model_id,
            "ready": False,
            "resolved_device": resolved_device,
            "model_source": "invalid",
            "requires_network": False,
            "reason": f"Unsupported Depth Anything device: {resolved_device}",
            "dependencies": dependencies,
        }

    selected = model_id.strip()
    if not selected:
        return {
            "provider_id": provider_id,
            "model_id": model_id,
            "ready": False,
            "resolved_device": resolved_device,
            "model_source": "invalid",
            "requires_network": False,
            "reason": "Choose a Depth Anything model ID or local checkpoint directory.",
            "dependencies": dependencies,
        }

    local_path = Path(selected).expanduser()
    if local_path.exists() or _looks_like_local_model_path(selected):
        ready, reason = _local_depth_checkpoint_status(
            local_path,
            metric_required=provider_id == "depth_anything_v2_metric",
        )
        return {
            "provider_id": provider_id,
            "model_id": model_id,
            "ready": ready,
            "resolved_device": resolved_device,
            "model_source": "local_path" if ready else "missing",
            "requires_network": False,
            "reason": reason,
            "dependencies": dependencies,
        }

    try:
        from huggingface_hub import snapshot_download

        cached_path = Path(
            snapshot_download(
                repo_id=selected,
                local_files_only=True,
                allow_patterns=[
                    "config.json",
                    "preprocessor_config.json",
                    "*.safetensors",
                    "*.bin",
                    "*.index.json",
                ],
            )
        )
        ready, reason = _local_depth_checkpoint_status(
            cached_path,
            metric_required=provider_id == "depth_anything_v2_metric",
        )
        if ready:
            return {
                "provider_id": provider_id,
                "model_id": model_id,
                "ready": True,
                "resolved_device": resolved_device,
                "model_source": "huggingface_cache",
                "requires_network": False,
                "reason": None,
                "dependencies": dependencies,
            }
        cached_reason = reason
    except Exception:
        cached_reason = "The selected model is not present in the local Hugging Face cache."

    if local_files_only:
        return {
            "provider_id": provider_id,
            "model_id": model_id,
            "ready": False,
            "resolved_device": resolved_device,
            "model_source": "missing",
            "requires_network": False,
            "reason": cached_reason,
            "dependencies": dependencies,
        }
    return {
        "provider_id": provider_id,
        "model_id": model_id,
        "ready": True,
        "resolved_device": resolved_device,
        "model_source": "remote",
        "requires_network": True,
        "reason": "The checkpoint is not cached and will require an explicit network download.",
        "dependencies": dependencies,
    }


def generate_depth_map(
    image_path: Path,
    *,
    provider_id: str,
    model_id: str,
    device: str,
    local_files_only: bool,
    maximum_metric_depth: float | None,
) -> tuple[NDArray[Any], dict[str, Any]]:
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
