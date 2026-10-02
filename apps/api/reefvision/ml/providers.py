"""Detection and interactive assist provider integrations."""
# mypy: disable-error-code="attr-defined"

from __future__ import annotations

import base64
from dataclasses import dataclass
from io import BytesIO
from math import isfinite
from pathlib import Path
from typing import Any, Protocol

from PIL import Image

from reefvision.domain.errors import ValidationError
from reefvision.ml.dependencies import (
    configure_provider_runtime,
    provider_spec,
    require_provider_ready,
)


@dataclass(frozen=True)
class PixelPoint:
    x: float
    y: float


@dataclass(frozen=True)
class PixelBox:
    x_min: float
    y_min: float
    x_max: float
    y_max: float


@dataclass(frozen=True)
class DetectionSettings:
    confidence_threshold: float
    iou_threshold: float
    device: str


@dataclass(frozen=True)
class DetectionModelMetadata:
    framework: str
    task: str
    provider_name: str
    provider_version: str
    class_labels: list[str]
    input_size: dict[str, Any] | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class DetectionPrediction:
    label: str
    class_index: int | None
    confidence: float
    box: PixelBox


@dataclass(frozen=True)
class AssistModelMetadata:
    framework: str
    task: str
    provider_name: str
    provider_version: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class BrushStroke:
    points: list[PixelPoint]
    brush_radius: float


@dataclass(frozen=True)
class AssistPrediction:
    mask: Any
    box: PixelBox
    score: float


class DetectionProvider(Protocol):
    provider_name: str

    @property
    def provider_version(self) -> str: ...

    def inspect_model(self, model_path: Path) -> DetectionModelMetadata: ...

    def load_model(self, model_path: Path, device: str) -> None: ...

    def predict(
        self, image_path: Path, settings: DetectionSettings
    ) -> list[DetectionPrediction]: ...

    def unload_model(self) -> None: ...


class AnnotationAssistProvider(Protocol):
    provider_name: str

    @property
    def provider_version(self) -> str: ...

    def inspect_model(self, model_path: Path) -> AssistModelMetadata: ...

    def load_model(self, model_path: Path, device: str) -> None: ...

    def prepare_image(self, image_path: Path) -> Any: ...

    def predict_from_points(
        self,
        prepared_image: Any,
        positive_points: list[PixelPoint],
        negative_points: list[PixelPoint],
        context_box: PixelBox | None = None,
    ) -> AssistPrediction: ...

    def predict_from_box(self, prepared_image: Any, box: PixelBox) -> AssistPrediction: ...

    def unload_model(self) -> None: ...


def ensure_finite_box(box: PixelBox) -> None:
    coordinates = (box.x_min, box.y_min, box.x_max, box.y_max)
    if not all(isfinite(float(value)) for value in coordinates):
        raise ValidationError("Bounding boxes must contain finite coordinates")
    if not (box.x_max > box.x_min and box.y_max > box.y_min):
        raise ValidationError("Bounding boxes must have positive width and height")


def require_local_checkpoint_path(
    model_path: Path,
    *,
    provider_label: str,
    allowed_suffixes: set[str],
) -> None:
    if model_path.suffix.lower() not in allowed_suffixes:
        suffixes = ", ".join(sorted(allowed_suffixes))
        raise ValidationError(
            f"{provider_label} currently supports only trusted local {suffixes} files"
        )
    if not model_path.is_file():
        raise ValidationError(
            f"{provider_label} requires an existing local checkpoint file. "
            "Automatic model downloads are disabled; select a local checkpoint explicitly."
        )


def infer_sam_variant(model_path: Path) -> str:
    name = model_path.name.lower()
    for variant in ("vit_h", "vit_l", "vit_b"):
        if variant in name:
            return variant
    raise ValidationError(
        "Could not infer the SAM variant from the checkpoint filename; "
        "include vit_b, vit_l, or vit_h"
    )


def resolve_torch_device(requested: str) -> str | int:
    normalized = requested.strip().lower()
    try:
        import torch
    except Exception as exc:  # pragma: no cover - exercised only when torch is unavailable
        raise ValidationError(f"Torch is required for model inference: {exc}") from exc

    if normalized in {"auto", ""}:
        return 0 if torch.cuda.is_available() else "cpu"
    if normalized in {"cpu"}:
        return "cpu"
    if normalized in {"cuda", "cuda:0", "gpu"}:
        if not torch.cuda.is_available():
            raise ValidationError("CUDA was requested but is not available")
        return 0
    raise ValidationError("Supported devices are auto, cpu, and cuda")


def mask_to_box(mask: Any) -> PixelBox:
    import numpy

    rows, cols = numpy.where(mask)
    if rows.size == 0 or cols.size == 0:
        raise ValidationError("The generated mask is empty")
    x_min = float(cols.min())
    x_max = float(cols.max() + 1)
    y_min = float(rows.min())
    y_max = float(rows.max() + 1)
    box = PixelBox(x_min=x_min, y_min=y_min, x_max=x_max, y_max=y_max)
    ensure_finite_box(box)
    return box


def mask_to_png_base64(mask: Any) -> str:
    image = Image.fromarray(mask.astype("uint8") * 160, mode="L")
    output = BytesIO()
    image.save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


def resample_stroke_points(points: list[PixelPoint], spacing: float) -> list[PixelPoint]:
    if not points:
        return []
    if len(points) == 1:
        return [points[0]]

    resampled = [points[0]]
    accumulated = 0.0
    previous = points[0]
    for current in points[1:]:
        dx = current.x - previous.x
        dy = current.y - previous.y
        segment = (dx**2 + dy**2) ** 0.5
        while segment > 0 and accumulated + segment >= spacing:
            remaining = spacing - accumulated
            ratio = remaining / segment
            point = PixelPoint(
                x=previous.x + dx * ratio,
                y=previous.y + dy * ratio,
            )
            resampled.append(point)
            previous = point
            dx = current.x - previous.x
            dy = current.y - previous.y
            segment = (dx**2 + dy**2) ** 0.5
            accumulated = 0.0
        accumulated += segment
        previous = current
    if resampled[-1] != points[-1]:
        resampled.append(points[-1])
    unique: list[PixelPoint] = []
    for point in resampled:
        if not unique or (unique[-1].x, unique[-1].y) != (point.x, point.y):
            unique.append(point)
    return unique


def stroke_bounds(strokes: list[BrushStroke]) -> PixelBox | None:
    xs: list[float] = []
    ys: list[float] = []
    for stroke in strokes:
        for point in stroke.points:
            xs.extend((point.x - stroke.brush_radius, point.x + stroke.brush_radius))
            ys.extend((point.y - stroke.brush_radius, point.y + stroke.brush_radius))
    if not xs or not ys:
        return None
    return PixelBox(min(xs), min(ys), max(xs), max(ys))


class UltralyticsDetectionProvider:
    provider_name = "ultralytics"
    provider_version = provider_spec("ultralytics").provider_version

    def __init__(self) -> None:
        self._model: Any | None = None

    def inspect_model(self, model_path: Path) -> DetectionModelMetadata:
        require_local_checkpoint_path(
            model_path,
            provider_label="Ultralytics detection",
            allowed_suffixes={".pt", ".pth"},
        )
        configure_provider_runtime()
        require_provider_ready(self.provider_name)
        try:
            from ultralytics import YOLO
        except Exception as exc:  # pragma: no cover - exercised only when dependency missing
            raise ValidationError(f"Ultralytics is unavailable: {exc}") from exc

        model = YOLO(str(model_path))
        task = str(getattr(model, "task", "detect") or "detect")
        if task not in {"detect", "segment", "pose"}:
            raise ValidationError(
                "This ReefVision release currently supports Ultralytics "
                "detect, segment, and pose checkpoints"
            )
        model_yaml = getattr(getattr(model, "model", None), "yaml", {}) or {}
        keypoint_shape = model_yaml.get("kpt_shape") if isinstance(model_yaml, dict) else None
        names = (
            getattr(model, "names", None)
            or getattr(getattr(model, "model", None), "names", None)
            or {}
        )
        if isinstance(names, dict):
            class_labels = [str(names[index]) for index in sorted(names)]
        else:
            class_labels = [str(item) for item in names]
        input_size = {"imgsz": getattr(model, "overrides", {}).get("imgsz")}
        return DetectionModelMetadata(
            framework="ultralytics",
            task=task,
            provider_name=self.provider_name,
            provider_version=self.provider_version,
            class_labels=class_labels,
            input_size=input_size,
            metadata={
                "trusted_checkpoint": True,
                "automatic_downloads_disabled": True,
                "explicit_checkpoint_required": True,
                "registered_execution_runtime": "pytorch",
                "proposal_geometry": "keypoints+bbox" if task == "pose" else "bounding_box",
                "segmentation_masks_exposed_in_editor": False,
                "pose_keypoint_shape": (
                    list(keypoint_shape)
                    if task == "pose" and isinstance(keypoint_shape, (list, tuple))
                    else None
                ),
            },
        )

    def load_model(self, model_path: Path, device: str) -> None:
        require_local_checkpoint_path(
            model_path,
            provider_label="Ultralytics detection",
            allowed_suffixes={".pt", ".pth"},
        )
        configure_provider_runtime()
        require_provider_ready(self.provider_name)
        try:
            from ultralytics import YOLO
        except Exception as exc:  # pragma: no cover
            raise ValidationError(f"Ultralytics is unavailable: {exc}") from exc
        resolve_torch_device(device)
        self._model = YOLO(str(model_path))

    def predict(self, image_path: Path, settings: DetectionSettings) -> list[DetectionPrediction]:
        if self._model is None:
            raise ValidationError("The detector model is not loaded")
        resolved_device = resolve_torch_device(settings.device)
        results = self._model.predict(
            str(image_path),
            conf=settings.confidence_threshold,
            iou=settings.iou_threshold,
            device=resolved_device,
            verbose=False,
        )
        predictions: list[DetectionPrediction] = []
        for result in results:
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            xyxy = boxes.xyxy.tolist()
            confidences = boxes.conf.tolist()
            classes = boxes.cls.tolist()
            names = getattr(result, "names", None) or getattr(self._model, "names", None) or {}
            for index, coords in enumerate(xyxy):
                class_index = int(classes[index]) if index < len(classes) else None
                label = (
                    str(names.get(class_index, class_index))
                    if isinstance(names, dict)
                    else str(names[class_index])
                    if class_index is not None and class_index < len(names)
                    else str(class_index)
                )
                predictions.append(
                    DetectionPrediction(
                        label=label,
                        class_index=class_index,
                        confidence=float(confidences[index]),
                        box=PixelBox(
                            x_min=float(coords[0]),
                            y_min=float(coords[1]),
                            x_max=float(coords[2]),
                            y_max=float(coords[3]),
                        ),
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


class SegmentAnythingAssistProvider:
    provider_name = "segment_anything"
    provider_version = provider_spec("segment_anything").provider_version

    def __init__(self) -> None:
        self._sam: Any | None = None

    def inspect_model(self, model_path: Path) -> AssistModelMetadata:
        require_local_checkpoint_path(
            model_path,
            provider_label="Segment Anything assist",
            allowed_suffixes={".pt", ".pth"},
        )
        configure_provider_runtime()
        require_provider_ready(self.provider_name)
        variant = infer_sam_variant(model_path)
        return AssistModelMetadata(
            framework="segment_anything",
            task="assist_segmentation",
            provider_name=self.provider_name,
            provider_version=self.provider_version,
            metadata={
                "variant": variant,
                "trusted_checkpoint": True,
                "automatic_downloads_disabled": True,
                "explicit_checkpoint_required": True,
                "registered_execution_runtime": "pytorch",
            },
        )

    def load_model(self, model_path: Path, device: str) -> None:
        require_local_checkpoint_path(
            model_path,
            provider_label="Segment Anything assist",
            allowed_suffixes={".pt", ".pth"},
        )
        configure_provider_runtime()
        require_provider_ready(self.provider_name)
        try:
            from segment_anything import sam_model_registry
        except Exception as exc:  # pragma: no cover
            raise ValidationError(f"segment_anything is unavailable: {exc}") from exc

        variant = infer_sam_variant(model_path)
        resolved_device = resolve_torch_device(device)
        sam = sam_model_registry[variant](checkpoint=str(model_path))
        sam.to(device=resolved_device)
        self._sam = sam

    def prepare_image(self, image_path: Path) -> Any:
        if self._sam is None:
            raise ValidationError("The assist model is not loaded")
        try:
            import cv2
            from segment_anything import SamPredictor
        except Exception as exc:  # pragma: no cover
            raise ValidationError(f"segment_anything dependencies are unavailable: {exc}") from exc

        image_bgr = cv2.imread(str(image_path))
        if image_bgr is None:
            raise ValidationError("Could not read the image for annotation assist")
        image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        predictor = SamPredictor(self._sam)
        predictor.set_image(image_rgb)
        return predictor

    def predict_from_points(
        self,
        prepared_image: Any,
        positive_points: list[PixelPoint],
        negative_points: list[PixelPoint],
        context_box: PixelBox | None = None,
    ) -> AssistPrediction:
        import numpy

        point_coords = numpy.array(
            [[point.x, point.y] for point in [*positive_points, *negative_points]],
            dtype="float32",
        )
        point_labels = numpy.array(
            [1] * len(positive_points) + [0] * len(negative_points),
            dtype="int32",
        )
        kwargs: dict[str, Any] = {"multimask_output": False}
        if point_coords.size:
            kwargs["point_coords"] = point_coords
            kwargs["point_labels"] = point_labels
        if context_box is not None:
            kwargs["box"] = numpy.array(
                [context_box.x_min, context_box.y_min, context_box.x_max, context_box.y_max],
                dtype="float32",
            )
        masks, scores, _ = prepared_image.predict(**kwargs)
        mask = masks[0].astype(bool)
        return AssistPrediction(mask=mask, box=mask_to_box(mask), score=float(scores[0]))

    def predict_from_box(self, prepared_image: Any, box: PixelBox) -> AssistPrediction:
        import numpy

        masks, scores, _ = prepared_image.predict(
            box=numpy.array([box.x_min, box.y_min, box.x_max, box.y_max], dtype="float32"),
            multimask_output=False,
        )
        mask = masks[0].astype(bool)
        return AssistPrediction(mask=mask, box=mask_to_box(mask), score=float(scores[0]))

    def unload_model(self) -> None:
        self._sam = None
        try:  # pragma: no cover - depends on CUDA availability
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            return
