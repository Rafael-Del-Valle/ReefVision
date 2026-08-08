"""Provider-neutral image classification training and inference."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol, cast

from reefvision.domain.errors import ValidationError

CLASSIFICATION_TASK = "classify"


@dataclass(frozen=True)
class ClassificationScore:
    class_name: str
    confidence: float
    rank: int


@dataclass(frozen=True)
class ClassificationTrainingResult:
    checkpoint_path: Path
    metrics: dict[str, float]
    provider_version: str
    run_root: Path


class ClassificationProvider(Protocol):
    provider_id: str

    @property
    def provider_version(self) -> str: ...

    def train(
        self,
        dataset_root: Path,
        run_root: Path,
        *,
        architecture: str,
        epochs: int,
        image_size: int,
        batch: int,
        device: str,
    ) -> ClassificationTrainingResult: ...

    def predict(
        self,
        checkpoint_path: Path,
        image_path: Path,
        *,
        top_k: int,
        device: str,
    ) -> list[ClassificationScore]: ...


class UltralyticsClassificationProvider:
    provider_id = "ultralytics"

    def __init__(self) -> None:
        try:
            self._ultralytics = cast(Any, import_module("ultralytics"))
        except ImportError as exc:
            raise ValidationError("Ultralytics is not installed") from exc

    @property
    def provider_version(self) -> str:
        return str(vars(self._ultralytics).get("__version__", "unknown"))

    @staticmethod
    def _device(device: str) -> str | int:
        normalized = device.strip().casefold()
        if normalized in {"", "auto"}:
            try:
                torch = cast(Any, import_module("torch"))
                return 0 if bool(torch.cuda.is_available()) else "cpu"
            except ImportError:
                return "cpu"
        if normalized.isdigit():
            return int(normalized)
        return normalized

    def train(
        self,
        dataset_root: Path,
        run_root: Path,
        *,
        architecture: str,
        epochs: int,
        image_size: int,
        batch: int,
        device: str,
    ) -> ClassificationTrainingResult:
        if not dataset_root.is_dir():
            raise ValidationError("Classification dataset directory is missing")
        run_root.parent.mkdir(parents=True, exist_ok=True)
        model = self._ultralytics.YOLO(architecture)
        result = model.train(
            data=str(dataset_root),
            task="classify",
            epochs=epochs,
            imgsz=image_size,
            batch=batch,
            device=self._device(device),
            project=str(run_root.parent),
            name=run_root.name,
            exist_ok=True,
            verbose=False,
        )
        checkpoint = run_root / "weights" / "best.pt"
        if not checkpoint.is_file():
            checkpoint = run_root / "weights" / "last.pt"
        if not checkpoint.is_file():
            raise ValidationError("Classification training completed without a checkpoint")
        raw_metrics = getattr(result, "results_dict", {})
        metrics = {
            str(key): float(value)
            for key, value in dict(raw_metrics).items()
            if isinstance(value, (int, float))
        }
        return ClassificationTrainingResult(
            checkpoint_path=checkpoint,
            metrics=metrics,
            provider_version=self.provider_version,
            run_root=run_root,
        )

    def predict(
        self,
        checkpoint_path: Path,
        image_path: Path,
        *,
        top_k: int,
        device: str,
    ) -> list[ClassificationScore]:
        if not checkpoint_path.is_file():
            raise ValidationError("Classifier checkpoint is missing")
        if not image_path.is_file():
            raise ValidationError("Classification source image is missing")
        model = self._ultralytics.YOLO(str(checkpoint_path))
        results = model.predict(
            source=str(image_path),
            device=self._device(device),
            verbose=False,
        )
        if not results:
            raise ValidationError("Classifier returned no result")
        result = results[0]
        probabilities = getattr(result, "probs", None)
        if probabilities is None:
            raise ValidationError("Classifier result did not contain probabilities")
        indices = list(getattr(probabilities, "top5", []))[:top_k]
        confidences = list(getattr(probabilities, "top5conf", []))[:top_k]
        names = dict(getattr(result, "names", {}))
        scores: list[ClassificationScore] = []
        for rank, (index, confidence) in enumerate(
            zip(indices, confidences, strict=False), start=1
        ):
            confidence_value = float(
                confidence.item() if hasattr(confidence, "item") else confidence
            )
            scores.append(
                ClassificationScore(
                    class_name=str(names.get(int(index), index)),
                    confidence=confidence_value,
                    rank=rank,
                )
            )
        return scores


def classification_provider_for_name(provider_id: str) -> ClassificationProvider:
    normalized = provider_id.strip().casefold()
    if normalized == "ultralytics":
        return UltralyticsClassificationProvider()
    raise ValidationError(f"Unsupported classification provider: {provider_id}")
