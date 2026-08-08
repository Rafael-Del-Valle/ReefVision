"""Transformers-backed Depth Anything V2 provider for local ReefVision bundles."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Protocol

from PIL import Image

from reefvision.domain.errors import ValidationError
from reefvision.ml.advanced_provider_contracts import DepthPrediction
from reefvision.ml.model_bundles import (
    extracted_transformers_bundle,
    inspect_transformers_bundle,
)
from reefvision.ml.providers import resolve_torch_device


@dataclass(frozen=True, slots=True)
class DepthModelMetadata:
    framework: str
    task: str
    provider_name: str
    provider_version: str
    metadata: dict[str, object]


class DepthRegistrationProvider(Protocol):
    provider_name: str
    provider_version: str

    def inspect_model(self, model_path: Path) -> DepthModelMetadata: ...

    def load_model(self, model_path: Path, device: str) -> None: ...

    def predict_depth(
        self,
        image_path: Path,
        output_path: Path,
        *,
        device: str,
    ) -> DepthPrediction: ...

    def unload_model(self) -> None: ...


def _transformers_version() -> str:
    try:
        return version("transformers")
    except PackageNotFoundError:
        return "unavailable"


def _torch_device_name(requested: str) -> str:
    resolved = resolve_torch_device(requested)
    return f"cuda:{resolved}" if isinstance(resolved, int) else str(resolved)


def _is_depth_anything_config(config: dict[str, object]) -> bool:
    model_type = str(config.get("model_type") or "").casefold()
    architectures = config.get("architectures")
    architecture_names = (
        [str(item).casefold() for item in architectures]
        if isinstance(architectures, list)
        else []
    )
    return "depth_anything" in model_type or any(
        "depthanything" in item.replace("_", "") for item in architecture_names
    )


class TransformersDepthAnythingV2Provider:
    provider_name = "depth_anything_v2"

    def __init__(self) -> None:
        self._model: Any | None = None
        self._processor: Any | None = None
        self._device = "cpu"

    @property
    def provider_version(self) -> str:
        return _transformers_version()

    def inspect_model(self, model_path: Path) -> DepthModelMetadata:
        config, _ = inspect_transformers_bundle(model_path)
        if not _is_depth_anything_config(config):
            raise ValidationError(
                "The selected model bundle does not declare a Depth Anything architecture"
            )
        return DepthModelMetadata(
            framework="transformers",
            task="relative_depth",
            provider_name=self.provider_name,
            provider_version=self.provider_version,
            metadata={
                "model_type": config.get("model_type"),
                "architectures": config.get("architectures", []),
                "trusted_checkpoint": True,
                "automatic_downloads_disabled": True,
                "explicit_checkpoint_required": True,
                "registered_execution_runtime": "pytorch",
                "bundle_format": "transformers_zip_v1",
                "depth_kind": "relative",
                "metric_depth": False,
            },
        )

    def load_model(self, model_path: Path, device: str) -> None:
        self.inspect_model(model_path)
        try:
            from transformers import AutoImageProcessor, AutoModelForDepthEstimation
        except Exception as exc:  # pragma: no cover - optional provider pack
            raise ValidationError(
                "Depth Anything V2 requires the optional Transformers provider pack: "
                f"{exc}"
            ) from exc
        model_root = extracted_transformers_bundle(model_path)
        resolved_device = _torch_device_name(device)
        try:
            processor = AutoImageProcessor.from_pretrained(
                model_root,
                local_files_only=True,
            )
            model = AutoModelForDepthEstimation.from_pretrained(
                model_root,
                local_files_only=True,
            )
            model = model.to(resolved_device).eval()
        except Exception as exc:
            raise ValidationError(
                f"Could not load the local Depth Anything V2 bundle: {exc}"
            ) from exc
        self._processor = processor
        self._model = model
        self._device = resolved_device

    def predict_depth(
        self,
        image_path: Path,
        output_path: Path,
        *,
        device: str,
    ) -> DepthPrediction:
        if self._model is None or self._processor is None:
            raise ValidationError("The Depth Anything V2 model is not loaded")
        requested_device = _torch_device_name(device)
        if requested_device != self._device:
            raise ValidationError(
                "Depth model device changed after loading; reload the provider before inference"
            )
        try:
            import numpy
            import torch
        except Exception as exc:  # pragma: no cover
            raise ValidationError(f"Depth inference dependencies are unavailable: {exc}") from exc
        try:
            image = Image.open(image_path).convert("RGB")
            inputs = self._processor(images=image, return_tensors="pt").to(self._device)
            with torch.inference_mode():
                outputs = self._model(**inputs)
            processed = self._processor.post_process_depth_estimation(
                outputs,
                target_sizes=[(image.height, image.width)],
            )
            depth_tensor = processed[0]["predicted_depth"]
            depth = depth_tensor.detach().cpu().numpy().astype("float32")
        except Exception as exc:
            if isinstance(exc, ValidationError):
                raise
            raise ValidationError(f"Depth Anything V2 inference failed: {exc}") from exc

        minimum = float(depth.min())
        maximum = float(depth.max())
        output_path.parent.mkdir(parents=True, exist_ok=True)
        relative_depth_path = output_path.with_suffix(".npy")
        preview_path = output_path.with_suffix(".png")
        numpy.save(relative_depth_path, depth, allow_pickle=False)
        span = maximum - minimum
        normalized = (
            numpy.zeros_like(depth, dtype="float32")
            if span <= 0
            else (depth - minimum) / span
        )
        preview = Image.fromarray((normalized * 65535.0).clip(0, 65535).astype("uint16"), mode="I;16")
        preview.save(preview_path, format="PNG")
        return DepthPrediction(
            width=image.width,
            height=image.height,
            relative_depth_path=relative_depth_path,
            preview_path=preview_path,
            minimum_value=minimum,
            maximum_value=maximum,
        )

    def unload_model(self) -> None:
        self._model = None
        self._processor = None
        self._device = "cpu"
        try:  # pragma: no cover - depends on CUDA availability
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            return
