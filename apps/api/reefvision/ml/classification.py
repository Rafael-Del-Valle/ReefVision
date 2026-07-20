"""Ultralytics crop-classification inspection and inference."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reefvision.domain.errors import ValidationError
from reefvision.ml.dependencies import (
    configure_provider_runtime,
    provider_spec,
    require_provider_ready,
)
from reefvision.ml.providers import (
    DetectionModelMetadata,
    UltralyticsDetectionProvider,
    require_local_checkpoint_path,
    resolve_torch_device,
)

CLASSIFICATION_TASK = "classify"
CLASSIFIER_PURPOSE = "classifier"
ULTRALYTICS_PROVIDER_ID = "ultralytics"


@dataclass(frozen=True)
class ClassificationResult:
    label: str
    class_index: int
    confidence: float
    probabilities: dict[str, float]


class UltralyticsClassificationRegistrationProvider(UltralyticsDetectionProvider):
    """Reuse trusted-checkpoint registration while enforcing task=classify."""

    def inspect_model(self, model_path: Path) -> DetectionModelMetadata:
        require_local_checkpoint_path(
            model_path,
            provider_label="Ultralytics classification",
            allowed_suffixes={".pt", ".pth"},
        )
        configure_provider_runtime()
        require_provider_ready(ULTRALYTICS_PROVIDER_ID)
        try:
            from ultralytics import YOLO  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - dependency failure
            raise ValidationError(f"Ultralytics is unavailable: {exc}") from exc
        model = YOLO(str(model_path))
        task = str(getattr(model, "task", "") or "")
        if task != CLASSIFICATION_TASK:
            raise ValidationError(
                "Classifier registration requires an Ultralytics classification checkpoint"
            )
        names = (
            getattr(model, "names", None)
            or getattr(getattr(model, "model", None), "names", None)
            or {}
        )
        if isinstance(names, dict):
            labels = [str(names[index]) for index in sorted(names)]
        else:
            labels = [str(item) for item in names]
        return DetectionModelMetadata(
            framework="ultralytics",
            task=CLASSIFICATION_TASK,
            provider_name=ULTRALYTICS_PROVIDER_ID,
            provider_version=provider_spec(ULTRALYTICS_PROVIDER_ID).provider_version,
            class_labels=labels,
            input_size={"imgsz": getattr(model, "overrides", {}).get("imgsz")},
            metadata={
                "trusted_checkpoint": True,
                "automatic_downloads_disabled": True,
                "explicit_checkpoint_required": True,
                "registered_execution_runtime": "pytorch",
                "classification_scope": "annotation_crop",
            },
        )


class UltralyticsClassificationProvider:
    provider_name = ULTRALYTICS_PROVIDER_ID
    provider_version = provider_spec(ULTRALYTICS_PROVIDER_ID).provider_version

    def __init__(self) -> None:
        self._model: Any | None = None

    def load_model(self, model_path: Path, device: str) -> None:
        require_local_checkpoint_path(
            model_path,
            provider_label="Ultralytics classification",
            allowed_suffixes={".pt", ".pth"},
        )
        configure_provider_runtime()
        require_provider_ready(self.provider_name)
        try:
            from ultralytics import YOLO  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover
            raise ValidationError(f"Ultralytics is unavailable: {exc}") from exc
        resolve_torch_device(device)
        model = YOLO(str(model_path))
        if str(getattr(model, "task", "") or "") != CLASSIFICATION_TASK:
            raise ValidationError("The selected model is not an Ultralytics classifier")
        self._model = model

    def predict(self, image_path: Path, *, device: str) -> ClassificationResult:
        if self._model is None:
            raise ValidationError("The classifier model is not loaded")
        results = self._model.predict(
            str(image_path),
            device=resolve_torch_device(device),
            verbose=False,
        )
        if not results:
            raise ValidationError("The classifier returned no result")
        result = results[0]
        probabilities = getattr(result, "probs", None)
        if probabilities is None:
            raise ValidationError("The classifier did not return class probabilities")
        top_index = int(probabilities.top1)
        top_confidence = float(probabilities.top1conf)
        names = getattr(result, "names", None) or getattr(self._model, "names", None) or {}
        if isinstance(names, dict):
            label = str(names.get(top_index, top_index))
            probability_map = {
                str(names.get(index, index)): float(value)
                for index, value in enumerate(probabilities.data.tolist())
            }
        else:
            label = str(names[top_index]) if top_index < len(names) else str(top_index)
            probability_map = {
                str(names[index]) if index < len(names) else str(index): float(value)
                for index, value in enumerate(probabilities.data.tolist())
            }
        return ClassificationResult(
            label=label,
            class_index=top_index,
            confidence=top_confidence,
            probabilities=probability_map,
        )

    def unload_model(self) -> None:
        self._model = None
        try:  # pragma: no cover - depends on CUDA availability
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            return
