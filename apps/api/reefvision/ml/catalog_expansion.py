"""Runtime adapters for optional ReefVision catalog model packs.

The base desktop runtime already includes Ultralytics and Segment Anything. This
module extends those two validated runtimes to additional official checkpoint
families without adding another Python environment or silently downloading
weights during inference.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from reefvision.domain.errors import ValidationError
from reefvision.ml.dependencies import configure_provider_runtime, require_provider_ready
from reefvision.ml.providers import (
    AssistModelMetadata,
    AssistPrediction,
    DetectionModelMetadata,
    PixelBox,
    PixelPoint,
    SegmentAnythingAssistProvider as OriginalSegmentAnythingAssistProvider,
    UltralyticsDetectionProvider as BaseUltralyticsDetectionProvider,
    mask_to_box,
    require_local_checkpoint_path,
    resolve_torch_device,
)

_PATCHED = False


def _ultralytics_detection_model(model_path: Path) -> Any:
    """Instantiate the correct Ultralytics model class for a local checkpoint."""

    configure_provider_runtime()
    require_provider_ready("ultralytics")
    name = model_path.name.casefold()
    try:
        if name.startswith("rtdetr-"):
            from ultralytics import RTDETR

            return RTDETR(str(model_path))
        if "-world" in name:
            from ultralytics import YOLOWorld

            return YOLOWorld(str(model_path))
        if name.startswith("yoloe-"):
            from ultralytics import YOLOE

            return YOLOE(str(model_path))
        from ultralytics import YOLO

        return YOLO(str(model_path))
    except Exception as exc:  # pragma: no cover - depends on third-party runtime
        raise ValidationError(
            f"Ultralytics could not load {model_path.name}: {exc}"
        ) from exc


class ExpandedUltralyticsDetectionProvider(BaseUltralyticsDetectionProvider):
    """Ultralytics provider with RT-DETR, YOLO-World, and YOLOE dispatch."""

    def inspect_model(self, model_path: Path) -> DetectionModelMetadata:
        require_local_checkpoint_path(
            model_path,
            provider_label="Ultralytics vision",
            allowed_suffixes={".pt", ".pth"},
        )
        model = _ultralytics_detection_model(model_path)
        task = str(getattr(model, "task", "detect") or "detect")
        if task not in {"detect", "segment"}:
            raise ValidationError(
                "This ReefVision release currently supports only Ultralytics "
                "detect and segment checkpoints"
            )
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
                "proposal_geometry": "bounding_box",
                "segmentation_masks_exposed_in_editor": False,
                "expanded_catalog_runtime": True,
                "checkpoint_family": model_path.stem,
            },
        )

    def load_model(self, model_path: Path, device: str) -> None:
        require_local_checkpoint_path(
            model_path,
            provider_label="Ultralytics vision",
            allowed_suffixes={".pt", ".pth"},
        )
        resolve_torch_device(device)
        self._model = _ultralytics_detection_model(model_path)


class UnifiedSegmentAnythingAssistProvider:
    """Smart Mask adapter for original SAM and Ultralytics SAM-family checkpoints."""

    provider_name = "segment_anything"
    provider_version = "1.0+reefvision-pack"

    def __init__(self) -> None:
        self._delegate: OriginalSegmentAnythingAssistProvider | None = None
        self._model: Any | None = None
        self._device: str | int = "cpu"
        self._backend: str | None = None

    @staticmethod
    def _uses_original_sam(model_path: Path) -> bool:
        name = model_path.name.casefold()
        return model_path.suffix.casefold() == ".pth" or "sam_vit_" in name

    def inspect_model(self, model_path: Path) -> AssistModelMetadata:
        require_local_checkpoint_path(
            model_path,
            provider_label="Smart Mask",
            allowed_suffixes={".pt", ".pth"},
        )
        if self._uses_original_sam(model_path):
            return OriginalSegmentAnythingAssistProvider().inspect_model(model_path)

        configure_provider_runtime()
        require_provider_ready("ultralytics")
        name = model_path.name.casefold()
        if name.startswith("fastsam-"):
            backend = "fastsam"
            variant = model_path.stem
        elif name.startswith("sam2_"):
            backend = "ultralytics_sam2"
            variant = model_path.stem
        elif name == "mobile_sam.pt":
            backend = "ultralytics_mobilesam"
            variant = "mobile_sam"
        elif name == "sam_b.pt":
            backend = "ultralytics_sam"
            variant = "sam_b"
        else:
            raise ValidationError(
                "Unsupported Smart Mask checkpoint. Expected original SAM, SAM 2, "
                "MobileSAM, or FastSAM official weights."
            )
        return AssistModelMetadata(
            framework="ultralytics",
            task="assist_segmentation",
            provider_name=self.provider_name,
            provider_version=self.provider_version,
            metadata={
                "variant": variant,
                "backend": backend,
                "trusted_checkpoint": True,
                "automatic_downloads_disabled": True,
                "explicit_checkpoint_required": True,
                "registered_execution_runtime": "pytorch",
                "expanded_catalog_runtime": True,
            },
        )

    def load_model(self, model_path: Path, device: str) -> None:
        require_local_checkpoint_path(
            model_path,
            provider_label="Smart Mask",
            allowed_suffixes={".pt", ".pth"},
        )
        self.unload_model()
        if self._uses_original_sam(model_path):
            delegate = OriginalSegmentAnythingAssistProvider()
            delegate.load_model(model_path, device)
            self._delegate = delegate
            self._backend = "original_sam"
            return

        configure_provider_runtime()
        require_provider_ready("ultralytics")
        self._device = resolve_torch_device(device)
        name = model_path.name.casefold()
        try:
            if name.startswith("fastsam-"):
                from ultralytics import FastSAM

                self._model = FastSAM(str(model_path))
                self._backend = "fastsam"
            else:
                from ultralytics import SAM

                self._model = SAM(str(model_path))
                self._backend = "ultralytics_sam"
        except Exception as exc:  # pragma: no cover - depends on third-party runtime
            raise ValidationError(
                f"Smart Mask could not load {model_path.name}: {exc}"
            ) from exc

    def prepare_image(self, image_path: Path) -> Any:
        if self._delegate is not None:
            return self._delegate.prepare_image(image_path)
        if self._model is None:
            raise ValidationError("The Smart Mask model is not loaded")
        if not image_path.is_file():
            raise ValidationError("Smart Mask requires an existing local image")
        return image_path

    @staticmethod
    def _mask_result(results: Any) -> AssistPrediction:
        if not results:
            raise ValidationError("The Smart Mask model returned no result")
        result = results[0]
        masks = getattr(result, "masks", None)
        data = getattr(masks, "data", None) if masks is not None else None
        if data is None or len(data) == 0:
            raise ValidationError("The Smart Mask model returned no mask")
        array = data.detach().float().cpu().numpy()
        scores: list[float] = []
        boxes = getattr(result, "boxes", None)
        confidences = getattr(boxes, "conf", None) if boxes is not None else None
        if confidences is not None:
            scores = [float(value) for value in confidences.detach().cpu().tolist()]
        index = max(
            range(len(array)),
            key=lambda item: scores[item] if item < len(scores) else 0.0,
        )
        mask = array[index] > 0.5
        score = scores[index] if index < len(scores) else 1.0
        return AssistPrediction(mask=mask, box=mask_to_box(mask), score=score)

    def _predict(
        self,
        prepared_image: Any,
        *,
        points: list[list[float]] | None = None,
        labels: list[int] | None = None,
        box: PixelBox | None = None,
    ) -> AssistPrediction:
        if self._model is None:
            raise ValidationError("The Smart Mask model is not loaded")
        kwargs: dict[str, Any] = {
            "device": self._device,
            "verbose": False,
            "retina_masks": True,
        }
        if points:
            kwargs["points"] = points
            kwargs["labels"] = labels or [1] * len(points)
        if box is not None:
            kwargs["bboxes"] = [box.x_min, box.y_min, box.x_max, box.y_max]
        try:
            return self._mask_result(self._model(str(prepared_image), **kwargs))
        except ValidationError:
            raise
        except Exception as exc:  # pragma: no cover - depends on third-party runtime
            raise ValidationError(f"Smart Mask prediction failed: {exc}") from exc

    def predict_from_points(
        self,
        prepared_image: Any,
        positive_points: list[PixelPoint],
        negative_points: list[PixelPoint],
        context_box: PixelBox | None = None,
    ) -> AssistPrediction:
        if self._delegate is not None:
            return self._delegate.predict_from_points(
                prepared_image,
                positive_points,
                negative_points,
                context_box,
            )
        points = [
            [point.x, point.y] for point in [*positive_points, *negative_points]
        ]
        labels = [1] * len(positive_points) + [0] * len(negative_points)
        if not points and context_box is None:
            raise ValidationError("Smart Mask requires at least one point or a context box")
        return self._predict(
            prepared_image,
            points=points,
            labels=labels,
            box=context_box,
        )

    def predict_from_box(self, prepared_image: Any, box: PixelBox) -> AssistPrediction:
        if self._delegate is not None:
            return self._delegate.predict_from_box(prepared_image, box)
        return self._predict(prepared_image, box=box)

    def unload_model(self) -> None:
        if self._delegate is not None:
            self._delegate.unload_model()
        self._delegate = None
        self._model = None
        self._backend = None
        try:  # pragma: no cover - depends on CUDA availability
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            return


def apply_catalog_expansion_runtime_patches() -> None:
    """Install provider-factory adapters once during desktop startup."""

    global _PATCHED
    if _PATCHED:
        return
    from reefvision.ml import provider_hub

    setattr(
        provider_hub,
        "UltralyticsDetectionProvider",
        ExpandedUltralyticsDetectionProvider,
    )
    setattr(
        provider_hub,
        "SegmentAnythingAssistProvider",
        UnifiedSegmentAnythingAssistProvider,
    )
    _PATCHED = True
