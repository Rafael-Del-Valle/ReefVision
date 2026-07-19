"""Optional SAM-family image adapters with explicit local-checkpoint loading."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from reefvision.domain.errors import ValidationError
from reefvision.ml.providers import (
    AssistModelMetadata,
    AssistPrediction,
    PixelBox,
    PixelPoint,
    mask_to_box,
    require_local_checkpoint_path,
)


def _package_version(*names: str) -> str:
    for name in names:
        try:
            return version(name)
        except PackageNotFoundError:
            continue
    return "unknown"


def _device_string(requested: str) -> str:
    normalized = requested.strip().casefold()
    try:
        import torch
    except Exception as exc:
        raise ValidationError(f"Torch is required for SAM-family inference: {exc}") from exc
    if normalized in {"", "auto", "gpu", "cuda"}:
        return "cuda:0" if torch.cuda.is_available() else "cpu"
    if normalized.startswith("cuda") and not torch.cuda.is_available():
        raise ValidationError("CUDA was requested but is unavailable")
    if normalized == "cpu" or normalized.startswith("cuda") or normalized == "mps":
        return requested
    raise ValidationError("Supported devices are auto, cpu, cuda[:index], and mps")


def _points_payload(
    positive_points: list[PixelPoint],
    negative_points: list[PixelPoint],
) -> tuple[np.ndarray | None, np.ndarray | None]:
    points = [*positive_points, *negative_points]
    if not points:
        return None, None
    return (
        np.asarray([[point.x, point.y] for point in points], dtype=np.float32),
        np.asarray(
            [1] * len(positive_points) + [0] * len(negative_points),
            dtype=np.int32,
        ),
    )


def _box_array(box: PixelBox | None) -> np.ndarray | None:
    if box is None:
        return None
    return np.asarray(
        [box.x_min, box.y_min, box.x_max, box.y_max], dtype=np.float32
    )


def _prediction(masks: Any, scores: Any) -> AssistPrediction:
    mask_array = np.asarray(masks)
    if mask_array.ndim >= 3:
        mask_array = mask_array[0]
    mask = mask_array.astype(bool)
    score_array = np.asarray(scores).reshape(-1)
    score = float(score_array[0]) if score_array.size else 1.0
    return AssistPrediction(mask=mask, box=mask_to_box(mask), score=score)


class _PredictorAdapter:
    provider_name = "sam_family"
    provider_version = "unknown"
    framework = "sam_family"
    allowed_suffixes = {".pt", ".pth"}

    def __init__(self) -> None:
        self._model: Any | None = None
        self._device = "cpu"

    def inspect_model(self, model_path: Path) -> AssistModelMetadata:
        require_local_checkpoint_path(
            model_path,
            provider_label=self.provider_name,
            allowed_suffixes=self.allowed_suffixes,
        )
        return AssistModelMetadata(
            framework=self.framework,
            task="assist_segmentation",
            provider_name=self.provider_name,
            provider_version=self.provider_version,
            metadata={
                "trusted_checkpoint": True,
                "automatic_downloads_disabled": True,
                "explicit_checkpoint_required": True,
                "registered_execution_runtime": "pytorch",
                "checkpoint_filename": model_path.name,
            },
        )

    def predict_from_points(
        self,
        prepared_image: Any,
        positive_points: list[PixelPoint],
        negative_points: list[PixelPoint],
        context_box: PixelBox | None = None,
    ) -> AssistPrediction:
        if not positive_points:
            raise ValidationError("SAM-family point prompting requires a positive point")
        point_coords, point_labels = _points_payload(positive_points, negative_points)
        masks, scores, _logits = prepared_image.predict(
            point_coords=point_coords,
            point_labels=point_labels,
            box=_box_array(context_box),
            multimask_output=False,
        )
        return _prediction(masks, scores)

    def predict_from_box(self, prepared_image: Any, box: PixelBox) -> AssistPrediction:
        masks, scores, _logits = prepared_image.predict(
            point_coords=None,
            point_labels=None,
            box=_box_array(box),
            multimask_output=False,
        )
        return _prediction(masks, scores)

    def unload_model(self) -> None:
        self._model = None
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            return


class MobileSAMAssistProvider(_PredictorAdapter):
    provider_name = "mobilesam"
    provider_version = _package_version("mobile-sam", "mobile_sam")
    framework = "mobile_sam"

    def load_model(self, model_path: Path, device: str) -> None:
        require_local_checkpoint_path(
            model_path,
            provider_label="MobileSAM assist",
            allowed_suffixes=self.allowed_suffixes,
        )
        try:
            from mobile_sam import sam_model_registry
        except Exception as exc:
            raise ValidationError(f"MobileSAM is unavailable: {exc}") from exc
        self._device = _device_string(device)
        variant = "vit_t"
        name = model_path.name.casefold()
        if "vit_b" in name:
            variant = "vit_b"
        if variant not in sam_model_registry:
            variant = next(iter(sam_model_registry))
        model = sam_model_registry[variant](checkpoint=str(model_path))
        model.to(device=self._device)
        model.eval()
        self._model = model

    def prepare_image(self, image_path: Path) -> Any:
        if self._model is None:
            raise ValidationError("The MobileSAM model is not loaded")
        try:
            from mobile_sam import SamPredictor
        except Exception as exc:
            raise ValidationError(f"MobileSAM predictor is unavailable: {exc}") from exc
        with Image.open(image_path) as source:
            image = np.asarray(source.convert("RGB"))
        predictor = SamPredictor(self._model)
        predictor.set_image(image)
        return predictor


class EfficientViTSAMAssistProvider(_PredictorAdapter):
    provider_name = "efficientvit_sam"
    provider_version = _package_version("efficientvit", "efficientvit-sam")
    framework = "efficientvit_sam"

    def load_model(self, model_path: Path, device: str) -> None:
        require_local_checkpoint_path(
            model_path,
            provider_label="EfficientViT-SAM assist",
            allowed_suffixes=self.allowed_suffixes,
        )
        try:
            from efficientvit.sam_model_zoo import create_sam_model
        except Exception as exc:
            raise ValidationError(f"EfficientViT-SAM is unavailable: {exc}") from exc
        self._device = _device_string(device)
        filename = model_path.name.casefold()
        variant = next(
            (item for item in ("xl1", "xl0", "l2", "l1", "l0") if item in filename),
            "l0",
        )
        try:
            model = create_sam_model(
                name=variant,
                pretrained=False,
                weight_url=str(model_path),
            )
        except TypeError:
            try:
                model = create_sam_model(variant, False, str(model_path))
            except Exception as exc:
                raise ValidationError(
                    "The installed EfficientViT-SAM package does not expose a compatible model factory"
                ) from exc
        model.to(device=self._device)
        model.eval()
        self._model = model

    def prepare_image(self, image_path: Path) -> Any:
        if self._model is None:
            raise ValidationError("The EfficientViT-SAM model is not loaded")
        try:
            from efficientvit.models.efficientvit.sam import SamPredictor
        except Exception as exc:
            raise ValidationError(f"EfficientViT-SAM predictor is unavailable: {exc}") from exc
        with Image.open(image_path) as source:
            image = np.asarray(source.convert("RGB"))
        predictor = SamPredictor(self._model)
        predictor.set_image(image)
        return predictor


def infer_sam2_config(model_path: Path) -> str:
    name = model_path.name.casefold().replace("-", "_")
    version_prefix = "configs/sam2.1" if "2.1" in name or "sam2_1" in name else "configs/sam2"
    variants = (
        (("hiera_tiny", "hiera_t", "tiny"), "sam2.1_hiera_t.yaml" if "sam2.1" in version_prefix else "sam2_hiera_t.yaml"),
        (("hiera_small", "hiera_s", "small"), "sam2.1_hiera_s.yaml" if "sam2.1" in version_prefix else "sam2_hiera_s.yaml"),
        (("hiera_base_plus", "base_plus", "hiera_b+", "base"), "sam2.1_hiera_b+.yaml" if "sam2.1" in version_prefix else "sam2_hiera_b+.yaml"),
        (("hiera_large", "hiera_l", "large"), "sam2.1_hiera_l.yaml" if "sam2.1" in version_prefix else "sam2_hiera_l.yaml"),
    )
    for tokens, config in variants:
        if any(token in name for token in tokens):
            return f"{version_prefix}/{config}"
    raise ValidationError(
        "Could not infer the SAM 2 configuration from the checkpoint filename; include tiny, small, base_plus, or large"
    )


class SAM2ImageAssistProvider(_PredictorAdapter):
    provider_name = "sam2"
    provider_version = _package_version("sam2")
    framework = "sam2"

    def inspect_model(self, model_path: Path) -> AssistModelMetadata:
        metadata = super().inspect_model(model_path)
        return AssistModelMetadata(
            framework=metadata.framework,
            task=metadata.task,
            provider_name=metadata.provider_name,
            provider_version=metadata.provider_version,
            metadata={**metadata.metadata, "config": infer_sam2_config(model_path)},
        )

    def load_model(self, model_path: Path, device: str) -> None:
        require_local_checkpoint_path(
            model_path,
            provider_label="SAM 2 assist",
            allowed_suffixes=self.allowed_suffixes,
        )
        try:
            from sam2.build_sam import build_sam2
        except Exception as exc:
            raise ValidationError(f"SAM 2 is unavailable: {exc}") from exc
        self._device = _device_string(device)
        config = infer_sam2_config(model_path)
        try:
            self._model = build_sam2(config, str(model_path), device=self._device)
        except Exception as exc:
            raise ValidationError(
                f"SAM 2 could not load checkpoint {model_path.name} with {config}: {exc}"
            ) from exc

    def prepare_image(self, image_path: Path) -> Any:
        if self._model is None:
            raise ValidationError("The SAM 2 model is not loaded")
        try:
            from sam2.sam2_image_predictor import SAM2ImagePredictor
        except Exception as exc:
            raise ValidationError(f"SAM 2 image predictor is unavailable: {exc}") from exc
        with Image.open(image_path) as source:
            image = np.asarray(source.convert("RGB"))
        predictor = SAM2ImagePredictor(self._model)
        predictor.set_image(image)
        return predictor
