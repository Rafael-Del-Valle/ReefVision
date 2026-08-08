"""Transformers-backed SAM2 image Prompt Assist provider."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from PIL import Image

from reefvision.domain.errors import ValidationError
from reefvision.ml.model_bundles import (
    extracted_transformers_bundle,
    inspect_transformers_bundle,
)
from reefvision.ml.providers import (
    AssistModelMetadata,
    AssistPrediction,
    PixelBox,
    PixelPoint,
    mask_to_box,
    resolve_torch_device,
)


def _transformers_version() -> str:
    try:
        return version("transformers")
    except PackageNotFoundError:
        return "unavailable"


def _torch_device_name(requested: str) -> str:
    resolved = resolve_torch_device(requested)
    return f"cuda:{resolved}" if isinstance(resolved, int) else str(resolved)


def _is_sam2_config(config: dict[str, object]) -> bool:
    model_type = str(config.get("model_type") or "").casefold()
    architectures = config.get("architectures")
    architecture_names = (
        [str(item).casefold() for item in architectures]
        if isinstance(architectures, list)
        else []
    )
    return model_type == "sam2" or any("sam2" in item for item in architecture_names)


class TransformersSam2AssistProvider:
    """Use a locally managed Transformers SAM2 bundle in the normal assist runtime."""

    provider_name = "sam2"

    def __init__(self) -> None:
        self._model: Any | None = None
        self._processor: Any | None = None
        self._device = "cpu"

    @property
    def provider_version(self) -> str:
        return _transformers_version()

    def inspect_model(self, model_path: Path) -> AssistModelMetadata:
        config, _ = inspect_transformers_bundle(model_path)
        if not _is_sam2_config(config):
            raise ValidationError("The selected model bundle does not declare a SAM2 architecture")
        return AssistModelMetadata(
            framework="transformers",
            task="assist_segmentation",
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
                "image_prompting": True,
                "video_propagation": False,
            },
        )

    def load_model(self, model_path: Path, device: str) -> None:
        self.inspect_model(model_path)
        try:
            from transformers import Sam2Model, Sam2Processor
        except Exception as exc:  # pragma: no cover - depends on optional provider pack
            raise ValidationError(
                "SAM2 requires the optional Transformers provider pack: " f"{exc}"
            ) from exc
        model_root = extracted_transformers_bundle(model_path)
        resolved_device = _torch_device_name(device)
        try:
            processor = Sam2Processor.from_pretrained(
                model_root,
                local_files_only=True,
            )
            model = Sam2Model.from_pretrained(
                model_root,
                local_files_only=True,
            )
            model = model.to(resolved_device).eval()
        except Exception as exc:
            raise ValidationError(f"Could not load the local SAM2 bundle: {exc}") from exc
        self._processor = processor
        self._model = model
        self._device = resolved_device

    def prepare_image(self, image_path: Path) -> Image.Image:
        if self._model is None or self._processor is None:
            raise ValidationError("The SAM2 assist model is not loaded")
        try:
            return Image.open(image_path).convert("RGB")
        except Exception as exc:
            raise ValidationError(f"Could not read the image for SAM2 assist: {exc}") from exc

    def _predict(
        self,
        image: Image.Image,
        *,
        positive_points: list[PixelPoint] | None = None,
        negative_points: list[PixelPoint] | None = None,
        box: PixelBox | None = None,
    ) -> AssistPrediction:
        if self._model is None or self._processor is None:
            raise ValidationError("The SAM2 assist model is not loaded")
        try:
            import torch
        except Exception as exc:  # pragma: no cover
            raise ValidationError(f"Torch is required for SAM2 inference: {exc}") from exc

        kwargs: dict[str, object] = {
            "images": image,
            "return_tensors": "pt",
        }
        points = [*(positive_points or []), *(negative_points or [])]
        if points:
            kwargs["input_points"] = [[[[point.x, point.y] for point in points]]]
            kwargs["input_labels"] = [
                [[1] * len(positive_points or []) + [0] * len(negative_points or [])]
            ]
        if box is not None:
            kwargs["input_boxes"] = [[[box.x_min, box.y_min, box.x_max, box.y_max]]]
        if not points and box is None:
            raise ValidationError("SAM2 needs at least one point or bounding-box prompt")

        try:
            inputs = self._processor(**kwargs).to(self._device)
            with torch.inference_mode():
                outputs = self._model(**inputs, multimask_output=False)
            masks = self._processor.post_process_masks(
                outputs.pred_masks.detach().cpu(),
                inputs["original_sizes"].detach().cpu(),
            )[0]
            mask_tensor = masks.reshape(-1, masks.shape[-2], masks.shape[-1])[0]
            mask = mask_tensor.detach().cpu().numpy().astype(bool)
            score_tensor = outputs.iou_scores.detach().cpu().reshape(-1)
            score = float(score_tensor[0]) if score_tensor.numel() else 0.0
        except Exception as exc:
            if isinstance(exc, ValidationError):
                raise
            raise ValidationError(f"SAM2 prompt inference failed: {exc}") from exc
        return AssistPrediction(mask=mask, box=mask_to_box(mask), score=score)

    def predict_from_points(
        self,
        prepared_image: Image.Image,
        positive_points: list[PixelPoint],
        negative_points: list[PixelPoint],
        context_box: PixelBox | None = None,
    ) -> AssistPrediction:
        return self._predict(
            prepared_image,
            positive_points=positive_points,
            negative_points=negative_points,
            box=context_box,
        )

    def predict_from_box(
        self,
        prepared_image: Image.Image,
        box: PixelBox,
    ) -> AssistPrediction:
        return self._predict(prepared_image, box=box)

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
