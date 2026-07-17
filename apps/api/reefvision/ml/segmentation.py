"""Instance-segmentation provider contracts and implementation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from reefvision.domain.errors import ValidationError
from reefvision.ml.dependencies import (
    configure_provider_runtime,
    require_provider_ready,
)
from reefvision.ml.providers import (
    DetectionSettings,
    PixelBox,
    ensure_finite_box,
    require_local_checkpoint_path,
    resolve_torch_device,
)


@dataclass(frozen=True)
class SegmentationPrediction:
    label: str
    class_index: int | None
    confidence: float
    box: PixelBox
    polygon: list[list[float]]


class SegmentationProvider(Protocol):
    provider_name: str
    provider_version: str

    def load_model(self, model_path: Path, device: str) -> None: ...

    def predict(
        self,
        image_path: Path,
        settings: DetectionSettings,
    ) -> list[SegmentationPrediction]: ...

    def unload_model(self) -> None: ...


class UltralyticsSegmentationProvider:
    provider_name = "ultralytics"

    def __init__(self) -> None:
        self._model: Any | None = None
        self.provider_version = "unknown"

    def load_model(self, model_path: Path, device: str) -> None:
        require_local_checkpoint_path(
            model_path,
            provider_label="Ultralytics segmentation",
            allowed_suffixes={".pt", ".pth"},
        )
        configure_provider_runtime()
        require_provider_ready(self.provider_name)
        try:
            import ultralytics
            from ultralytics import YOLO
        except Exception as exc:  # pragma: no cover - dependency failure
            raise ValidationError(
                f"Ultralytics is unavailable: {exc}"
            ) from exc
        resolve_torch_device(device)
        model = YOLO(str(model_path))
        task = str(getattr(model, "task", "") or "")
        if task != "segment":
            raise ValidationError(
                "The selected checkpoint is not an Ultralytics segmentation "
                "model"
            )
        self.provider_version = str(
            getattr(ultralytics, "__version__", "unknown")
        )
        self._model = model

    def predict(
        self,
        image_path: Path,
        settings: DetectionSettings,
    ) -> list[SegmentationPrediction]:
        if self._model is None:
            raise ValidationError("The segmentation model is not loaded")
        results = self._model.predict(
            str(image_path),
            conf=settings.confidence_threshold,
            iou=settings.iou_threshold,
            device=resolve_torch_device(settings.device),
            verbose=False,
        )
        predictions: list[SegmentationPrediction] = []
        for result in results:
            boxes = getattr(result, "boxes", None)
            masks = getattr(result, "masks", None)
            polygons = (
                getattr(masks, "xy", None) if masks is not None else None
            )
            if boxes is None or polygons is None:
                continue
            xyxy = boxes.xyxy.tolist()
            confidences = boxes.conf.tolist()
            classes = boxes.cls.tolist()
            names = (
                getattr(result, "names", None)
                or getattr(self._model, "names", None)
                or {}
            )
            for index, raw_polygon in enumerate(polygons):
                if index >= len(xyxy) or index >= len(confidences):
                    break
                points = [
                    [float(point[0]), float(point[1])]
                    for point in raw_polygon.tolist()
                ]
                if len({(point[0], point[1]) for point in points}) < 3:
                    continue
                coords = xyxy[index]
                box = PixelBox(
                    x_min=float(coords[0]),
                    y_min=float(coords[1]),
                    x_max=float(coords[2]),
                    y_max=float(coords[3]),
                )
                ensure_finite_box(box)
                class_index = (
                    int(classes[index]) if index < len(classes) else None
                )
                label = (
                    str(names.get(class_index, class_index))
                    if isinstance(names, dict)
                    else str(names[class_index])
                    if class_index is not None and class_index < len(names)
                    else str(class_index)
                )
                predictions.append(
                    SegmentationPrediction(
                        label=label,
                        class_index=class_index,
                        confidence=float(confidences[index]),
                        box=box,
                        polygon=points,
                    )
                )
        return predictions

    def unload_model(self) -> None:
        self._model = None
        try:  # pragma: no cover - depends on CUDA availability
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            return


def segmentation_provider_for_name(
    provider_name: str,
) -> SegmentationProvider:
    if provider_name.strip().casefold() == "ultralytics":
        return UltralyticsSegmentationProvider()
    raise ValidationError(
        f"Unsupported segmentation provider: {provider_name}"
    )
