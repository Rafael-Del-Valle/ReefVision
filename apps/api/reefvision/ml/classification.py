"""Ultralytics crop-classification inspection and inference."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from math import isfinite
from pathlib import Path
from typing import Any

from reefvision.config import Settings
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


def resolve_installed_classification_architecture(
    architecture: str,
    settings: Settings | None = None,
) -> Path:
    """Resolve a scratch classifier only from the installed Ultralytics package."""

    normalized = architecture.strip()
    if Path(normalized).name != normalized or not normalized.casefold().endswith("-cls.yaml"):
        raise ValidationError(
            "Scratch classification training requires a local *-cls.yaml architecture"
        )
    configure_provider_runtime(settings)
    try:
        models_root = Path(str(files("ultralytics.cfg").joinpath("models")))
    except Exception as exc:
        raise ValidationError(
            "The installed Ultralytics package does not expose its architecture registry"
        ) from exc
    matches = sorted(path.resolve() for path in models_root.rglob(normalized) if path.is_file())
    if not matches:
        raise ValidationError(
            "The selected classification architecture is not available in the installed "
            "pinned Ultralytics package"
        )
    if len(matches) > 1:
        raise ValidationError(
            "The selected classification architecture is ambiguous in the installed "
            "Ultralytics package"
        )
    return matches[0]


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
        raw_values = probabilities.data.tolist()
        if not isinstance(raw_values, list) or not raw_values:
            raise ValidationError("The classifier returned an empty probability vector")
        if any(isinstance(value, (list, tuple, dict)) for value in raw_values):
            raise ValidationError("The classifier returned an invalid probability-vector shape")
        try:
            values = [float(value) for value in raw_values]
        except (TypeError, ValueError) as exc:
            raise ValidationError("The classifier returned non-numeric probabilities") from exc
        if any(not isfinite(value) for value in values):
            raise ValidationError("The classifier returned non-finite probabilities")
        if any(value < -1e-6 or value > 1 + 1e-6 for value in values):
            raise ValidationError("The classifier returned probabilities outside the range [0, 1]")
        probability_sum = sum(values)
        if not isfinite(probability_sum) or abs(probability_sum - 1.0) > 1e-3:
            raise ValidationError("The classifier probability vector does not sum to one")

        top_index = int(probabilities.top1)
        if top_index < 0 or top_index >= len(values):
            raise ValidationError("The classifier returned an out-of-range top class index")
        top_confidence = float(probabilities.top1conf)
        if not isfinite(top_confidence):
            raise ValidationError("The classifier returned a non-finite top confidence")
        if abs(top_confidence - values[top_index]) > 1e-4:
            raise ValidationError(
                "The classifier top confidence does not match its probability vector"
            )
        computed_top_index = max(range(len(values)), key=values.__getitem__)
        if top_index != computed_top_index:
            raise ValidationError("The classifier top class does not match its highest probability")

        names = getattr(result, "names", None) or getattr(self._model, "names", None) or {}
        if isinstance(names, dict):
            labels = [str(names.get(index, index)) for index in range(len(values))]
        else:
            labels = [
                str(names[index]) if index < len(names) else str(index)
                for index in range(len(values))
            ]
        if len(set(labels)) != len(labels):
            raise ValidationError("The classifier returned duplicate probability labels")
        probability_map = dict(zip(labels, values, strict=True))
        return ClassificationResult(
            label=labels[top_index],
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
