"""Instance-segmentation provider contracts and implementation."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from io import BytesIO
from math import isfinite
from pathlib import Path
from typing import Any, Protocol, cast

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from reefvision.domain.errors import ValidationError
from reefvision.ml.dependencies import (
    configure_provider_runtime,
    require_provider_ready,
)
from reefvision.ml.mask_tools import normalize_ring, self_intersections
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
    polygon: list[list[float]] | None = None
    mask_png_bytes: bytes | None = None


MAX_REVIEW_POLYGON_POINTS = 2_000


def _reviewable_polygon(
    raw_polygon: Any,
    *,
    image_width: int,
    image_height: int,
) -> list[list[float]] | None:
    try:
        raw_points = raw_polygon.tolist() if hasattr(raw_polygon, "tolist") else raw_polygon
        if not isinstance(raw_points, (list, tuple)):
            return None
        points: list[tuple[float, float]] = []
        for raw_point in raw_points:
            if not isinstance(raw_point, (list, tuple)) or len(raw_point) != 2:
                return None
            point = (float(raw_point[0]), float(raw_point[1]))
            if not all(isfinite(value) for value in point):
                return None
            if not (0 <= point[0] <= image_width and 0 <= point[1] <= image_height):
                return None
            points.append(point)
        points = normalize_ring(points)
    except (TypeError, ValueError, OverflowError, ValidationError):
        return None
    if not 3 <= len(points) <= MAX_REVIEW_POLYGON_POINTS:
        return None
    if self_intersections(points):
        return None
    return [[x, y] for x, y in points]


def _as_numpy(value: Any) -> NDArray[Any] | None:
    try:
        detached = value.detach() if hasattr(value, "detach") else value
        on_cpu = detached.cpu() if hasattr(detached, "cpu") else detached
        array_value = on_cpu.numpy() if hasattr(on_cpu, "numpy") else on_cpu
        return np.asarray(array_value)
    except (AttributeError, TypeError, ValueError, RuntimeError):
        return None


def _instance_mask(mask_data: Any, index: int) -> NDArray[Any] | None:
    masks = _as_numpy(mask_data)
    if masks is None:
        return None
    if masks.ndim == 2:
        return masks if index == 0 else None
    if masks.ndim != 3 or index >= masks.shape[0]:
        return None
    return np.asarray(masks[index])


def _binary_mask_png(
    raw_mask: Any,
    *,
    image_width: int,
    image_height: int,
) -> bytes | None:
    mask = _as_numpy(raw_mask)
    if mask is None:
        return None
    mask = np.squeeze(mask)
    if mask.ndim != 2 or mask.size == 0:
        return None
    try:
        if not bool(np.isfinite(mask).all()):
            return None
        binary = mask > 0.5
    except (TypeError, ValueError):
        return None
    if not bool(binary.any()):
        return None
    image = Image.fromarray(binary.astype(np.uint8) * 255)
    if image.size != (image_width, image_height):
        image = image.resize((image_width, image_height), resample=Image.Resampling.NEAREST)
    if image.getbbox() is None:
        return None
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _polygon_at_index(polygons: Any, index: int) -> Any | None:
    if polygons is None:
        return None
    try:
        return polygons[index]
    except (IndexError, KeyError, TypeError):
        return None


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
            ultralytics = cast(Any, import_module("ultralytics"))
            yolo_class = ultralytics.YOLO
        except Exception as exc:  # pragma: no cover - dependency failure
            raise ValidationError(f"Ultralytics is unavailable: {exc}") from exc
        resolve_torch_device(device)
        model = yolo_class(str(model_path))
        task = str(getattr(model, "task", "") or "")
        if task != "segment":
            raise ValidationError(
                "The selected checkpoint is not an Ultralytics segmentation model"
            )
        self.provider_version = str(vars(ultralytics).get("__version__", "unknown"))
        self._model = model

    def predict(
        self,
        image_path: Path,
        settings: DetectionSettings,
    ) -> list[SegmentationPrediction]:
        if self._model is None:
            raise ValidationError("The segmentation model is not loaded")
        try:
            with Image.open(image_path) as source:
                image_width, image_height = source.size
        except OSError as exc:
            raise ValidationError("Could not read the image for segmentation inference") from exc
        results = self._model.predict(
            str(image_path),
            conf=settings.confidence_threshold,
            iou=settings.iou_threshold,
            device=resolve_torch_device(settings.device),
            retina_masks=True,
            verbose=False,
        )
        predictions: list[SegmentationPrediction] = []
        for result in results:
            boxes = getattr(result, "boxes", None)
            masks = getattr(result, "masks", None)
            if boxes is None or masks is None:
                continue
            try:
                polygons = getattr(masks, "xy", None)
            except Exception:
                # A provider polygon-conversion error must still permit raster fallback.
                polygons = None
            xyxy = _as_numpy(getattr(boxes, "xyxy", None))
            confidences = _as_numpy(getattr(boxes, "conf", None))
            classes = _as_numpy(getattr(boxes, "cls", None))
            mask_data = getattr(masks, "data", None)
            if xyxy is None or xyxy.ndim != 2 or xyxy.shape[1] < 4 or confidences is None:
                continue
            confidences = confidences.reshape(-1)
            classes = classes.reshape(-1) if classes is not None else None
            names = getattr(result, "names", None) or getattr(self._model, "names", None) or {}
            for index, coords in enumerate(xyxy):
                if index >= len(confidences):
                    break
                try:
                    confidence = float(confidences[index])
                    box = PixelBox(
                        x_min=float(coords[0]),
                        y_min=float(coords[1]),
                        x_max=float(coords[2]),
                        y_max=float(coords[3]),
                    )
                    if not isfinite(confidence) or not 0 <= confidence <= 1:
                        continue
                    if not all(
                        isfinite(value) for value in (box.x_min, box.y_min, box.x_max, box.y_max)
                    ):
                        continue
                    ensure_finite_box(box)
                except (TypeError, ValueError, OverflowError, ValidationError):
                    continue
                class_index = None
                if classes is not None and index < len(classes):
                    try:
                        raw_class_index = float(classes[index])
                        class_index = int(raw_class_index) if isfinite(raw_class_index) else None
                    except (TypeError, ValueError, OverflowError):
                        class_index = None
                label = (
                    str(names.get(class_index, class_index))
                    if isinstance(names, dict)
                    else str(names[class_index])
                    if (class_index is not None and 0 <= class_index < len(names))
                    else str(class_index)
                )
                polygon = _reviewable_polygon(
                    _polygon_at_index(polygons, index),
                    image_width=image_width,
                    image_height=image_height,
                )
                mask_png_bytes = None
                if polygon is None:
                    raw_mask = _instance_mask(mask_data, index)
                    if raw_mask is not None:
                        mask_png_bytes = _binary_mask_png(
                            raw_mask,
                            image_width=image_width,
                            image_height=image_height,
                        )
                    if mask_png_bytes is None:
                        continue
                predictions.append(
                    SegmentationPrediction(
                        label=label,
                        class_index=class_index,
                        confidence=confidence,
                        box=box,
                        polygon=polygon,
                        mask_png_bytes=mask_png_bytes,
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
    raise ValidationError(f"Unsupported segmentation provider: {provider_name}")
