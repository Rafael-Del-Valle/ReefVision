"""Lazy, one-model-at-a-time runtime for ReefVision model providers."""

from __future__ import annotations

import base64
import gc
import importlib.metadata
import importlib.util
import io
import math
import threading
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from reefvision.ml.provider_contract import (
    CancellationToken,
    LifecycleInferenceRequest,
    LifecycleInferenceResult,
    LifecycleProvider,
    ProviderLifecycleError,
    ProviderModelDefinition,
    ProviderOutOfMemoryError,
    ProviderState,
    ProviderUnavailableError,
)
from reefvision.ml.provider_verification import resolve_device, sha256_file


def _runtime_version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "missing"


def _is_out_of_memory(exc: BaseException) -> bool:
    name = type(exc).__name__.casefold()
    message = str(exc).casefold()
    return "outofmemory" in name or "out of memory" in message or "cuda oom" in message


def release_accelerator_memory() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        return


def _mask_png(mask: NDArray[Any]) -> str:
    buffer = io.BytesIO()
    Image.fromarray(mask.astype(np.uint8) * 255, mode="L").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _aligned_mask(mask: Any, width: int, height: int) -> NDArray[Any]:
    array = np.asarray(mask, dtype=np.float32)
    if array.ndim != 2:
        raise ProviderLifecycleError("Provider returned a mask with an invalid shape")
    if array.shape != (height, width):
        array = np.asarray(
            Image.fromarray(array).resize((width, height), resample=Image.Resampling.BILINEAR),
            dtype=np.float32,
        )
    return array > 0.5


def _safe_float(value: Any, *, default: float = 0.0) -> float:
    try:
        output = float(value)
    except (TypeError, ValueError):
        return default
    return output if math.isfinite(output) else default


class UltralyticsLifecycleProvider:
    provider_id = "ultralytics"

    def __init__(self) -> None:
        self._model: Any | None = None
        self._device = "cpu"
        self._model_id: str | None = None

    @staticmethod
    def _constructor(model: ProviderModelDefinition) -> Any:
        path = model.checkpoint_path
        if not path.is_file():
            raise ProviderUnavailableError(
                "Ultralytics requires an existing local checkpoint; "
                "automatic downloads are disabled"
            )
        name = path.name.casefold()
        try:
            ultralytics: Any = import_module("ultralytics")

            if name.startswith("rtdetr-"):
                return ultralytics.RTDETR(str(path))
            if "-world" in name:
                return ultralytics.YOLOWorld(str(path))
            if name.startswith("yoloe-"):
                return ultralytics.YOLOE(str(path))
            if name.startswith("fastsam-"):
                return ultralytics.FastSAM(str(path))
            if name in {"sam_b.pt", "sam2_b.pt", "mobile_sam.pt"}:
                return ultralytics.SAM(str(path))
            return ultralytics.YOLO(str(path))
        except ImportError as exc:
            raise ProviderUnavailableError(f"Ultralytics runtime is unavailable: {exc}") from exc

    def load(self, model: ProviderModelDefinition, device: str) -> None:
        self.unload()
        self._device = resolve_device(device)
        self._model = self._constructor(model)
        self._model_id = model.model_id

    def health_check(self) -> dict[str, Any]:
        if self._model is None:
            raise ProviderUnavailableError("No Ultralytics checkpoint is loaded")
        return {
            "loaded": True,
            "model_id": self._model_id,
            "device": self._device,
            "task": str(getattr(self._model, "task", "unknown")),
            "ultralytics_version": _runtime_version("ultralytics"),
        }

    def _set_world_classes(
        self,
        model: ProviderModelDefinition,
        text_prompts: list[str],
    ) -> dict[str, Any]:
        """Encode YOLO-World prompts from one verified local CLIP checkpoint."""

        checkpoint_value = model.metadata.get("clip_text_checkpoint_path")
        expected_checksum = str(model.metadata.get("clip_text_checkpoint_sha256") or "")
        checkpoint = Path(str(checkpoint_value)) if checkpoint_value else None
        if checkpoint is None or not checkpoint.is_file():
            raise ProviderUnavailableError(
                "YOLO-World requires the managed CLIP ViT-B/32 text checkpoint; "
                "automatic downloads are disabled"
            )
        observed_checksum = sha256_file(checkpoint)
        if not expected_checksum or observed_checksum != expected_checksum:
            raise ProviderUnavailableError(
                "The managed YOLO-World CLIP text checkpoint failed checksum verification"
            )
        if importlib.util.find_spec("clip") is None:
            raise ProviderUnavailableError(
                "YOLO-World text prompts require the pinned Ultralytics CLIP package"
            )
        try:
            import torch

            clip: Any = import_module("clip")
            runtime_model = self._model
            if runtime_model is None:
                raise ProviderUnavailableError("The YOLO-World checkpoint is not loaded")
            clip_model, _preprocess = clip.load(
                str(checkpoint),
                device=self._device,
                jit=False,
            )
            with torch.inference_mode():
                tokens = clip.tokenize(text_prompts, truncate=True).to(self._device)
                text_features = clip_model.encode_text(tokens).float()
                text_features /= text_features.norm(p=2, dim=-1, keepdim=True)
                text_features = text_features.reshape(1, len(text_prompts), -1)
            world_model = getattr(runtime_model, "model", None)
            if world_model is None or not hasattr(world_model, "txt_feats"):
                raise ProviderUnavailableError(
                    "The installed YOLO-World runtime cannot accept encoded text prompts"
                )
            world_model.txt_feats = text_features
            if getattr(world_model, "model", None):
                world_model.model[-1].nc = len(text_prompts)
            world_model.names = list(text_prompts)
            predictor = getattr(runtime_model, "predictor", None)
            if predictor is not None:
                predictor.model.names = list(text_prompts)
            del clip_model
            release_accelerator_memory()
        except ProviderUnavailableError:
            raise
        except Exception as exc:
            if _is_out_of_memory(exc):
                self.unload()
                raise ProviderOutOfMemoryError(
                    "YOLO-World text encoding exhausted device memory; the model was unloaded"
                ) from exc
            raise ProviderLifecycleError(f"YOLO-World local text encoding failed: {exc}") from exc
        return {
            "text_encoder": "CLIP ViT-B/32",
            "text_checkpoint_path": str(checkpoint),
            "text_checkpoint_sha256": observed_checksum,
            "text_checkpoint_managed": True,
        }

    def _predict_kwargs(
        self,
        model: ProviderModelDefinition,
        request: LifecycleInferenceRequest,
    ) -> dict[str, Any]:
        parameters = request.parameters
        kwargs: dict[str, Any] = {
            "device": self._device,
            "verbose": False,
            "conf": float(parameters.get("confidence", 0.25)),
            "iou": float(parameters.get("iou", 0.45)),
            "imgsz": int(parameters.get("imgsz", 640)),
        }
        if model.capabilities.mask_output:
            kwargs["retina_masks"] = True
        positive = list(parameters.get("positive_points") or [])
        negative = list(parameters.get("negative_points") or [])
        box = parameters.get("box")
        if positive or negative:
            if not model.capabilities.point_prompt:
                raise ProviderLifecycleError("The selected model does not support point prompts")
            if negative and not model.capabilities.negative_point_prompt:
                raise ProviderLifecycleError(
                    "The selected model does not support negative point prompts"
                )
            labels = [1] * len(positive) + [0] * len(negative)
            points = [*positive, *negative]
            if model.checkpoint_path.name.casefold().startswith("fastsam-"):
                # FastSAM's prompt adapter consumes an unbatched point list.
                kwargs["points"] = points
                kwargs["labels"] = labels
            else:
                # One outer batch dimension keeps positive and negative clicks
                # tied to the same candidate. A flat list is interpreted as one
                # object per point by SAM/SAM 2 and breaks mixed prompt batches.
                kwargs["points"] = [points]
                kwargs["labels"] = [labels]
        if box is not None:
            if not model.capabilities.box_prompt:
                raise ProviderLifecycleError("The selected model does not support box prompts")
            kwargs["bboxes"] = list(box)
        return kwargs

    def _normalize_results(
        self,
        model: ProviderModelDefinition,
        results: Any,
        source_path: Path,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        with Image.open(source_path) as source:
            width, height = source.size
        outputs: list[dict[str, Any]] = []
        mask_candidate_count = 0
        for result in results or []:
            boxes = getattr(result, "boxes", None)
            xyxy = boxes.xyxy.detach().float().cpu().tolist() if boxes is not None else []
            confidences = (
                boxes.conf.detach().float().cpu().tolist()
                if boxes is not None and getattr(boxes, "conf", None) is not None
                else []
            )
            classes = (
                boxes.cls.detach().float().cpu().tolist()
                if boxes is not None and getattr(boxes, "cls", None) is not None
                else []
            )
            names = getattr(result, "names", None) or getattr(self._model, "names", None) or {}
            masks = getattr(result, "masks", None)
            mask_data = getattr(masks, "data", None) if masks is not None else None
            polygons = getattr(masks, "xy", None) if masks is not None else None
            raw_masks: list[Any] = []
            if mask_data is not None:
                raw_masks = list(mask_data.detach().float().cpu().numpy())

            count = max(len(xyxy), len(raw_masks))
            for index in range(count):
                coords = xyxy[index] if index < len(xyxy) else None
                class_index = int(classes[index]) if index < len(classes) else None
                if isinstance(names, dict):
                    label = str(names.get(class_index, class_index))
                elif class_index is not None and class_index < len(names):
                    label = str(names[class_index])
                else:
                    label = str(class_index) if class_index is not None else "mask"
                proposal: dict[str, Any] = {
                    "rank": index + 1,
                    "label": label,
                    "class_index": class_index,
                    "confidence": _safe_float(
                        confidences[index] if index < len(confidences) else 1.0,
                        default=1.0,
                    ),
                    "source_width": width,
                    "source_height": height,
                }
                if coords is not None:
                    proposal["box"] = {
                        "x_min": _safe_float(coords[0]),
                        "y_min": _safe_float(coords[1]),
                        "x_max": _safe_float(coords[2]),
                        "y_max": _safe_float(coords[3]),
                    }
                polygon = (
                    polygons[index] if polygons is not None and index < len(polygons) else None
                )
                if polygon is not None and len(polygon) >= 3:
                    proposal["polygon"] = [
                        {"x": _safe_float(point[0]), "y": _safe_float(point[1])}
                        for point in polygon
                    ]
                    proposal["mask_representation"] = "polygon"
                elif index < len(raw_masks):
                    aligned = _aligned_mask(raw_masks[index], width, height)
                    if aligned.any():
                        proposal["raster_mask_png_base64"] = _mask_png(aligned)
                        proposal["mask_representation"] = "source_aligned_raster"
                if "polygon" in proposal or "raster_mask_png_base64" in proposal:
                    mask_candidate_count += 1
                outputs.append(proposal)
        outputs.sort(key=lambda item: float(item.get("confidence", 0.0)), reverse=True)
        for index, item in enumerate(outputs, start=1):
            item["rank"] = index
        return outputs, {
            "source_width": width,
            "source_height": height,
            "empty_result": not outputs,
            "mask_candidate_count": mask_candidate_count,
            "proposal_geometry": "mask" if model.capabilities.mask_output else "box",
        }

    def infer(
        self,
        model: ProviderModelDefinition,
        request: LifecycleInferenceRequest,
        cancellation: CancellationToken,
    ) -> LifecycleInferenceResult:
        if self._model is None or self._model_id != model.model_id:
            raise ProviderUnavailableError("The requested Ultralytics model is not loaded")
        if not request.source_path.is_file():
            raise ProviderUnavailableError("The local inference image is missing")
        cancellation.raise_if_cancelled()
        parameters = request.parameters
        text_prompts = [str(value).strip() for value in parameters.get("text_prompts", [])]
        text_prompts = [value for value in text_prompts if value]
        text_encoder_provenance: dict[str, Any] = {}
        if model.capabilities.text_prompt:
            if not text_prompts:
                raise ProviderLifecycleError(
                    "YOLO-World requires at least one explicit user-provided class prompt"
                )
            text_encoder_provenance = self._set_world_classes(model, text_prompts)
        kwargs = self._predict_kwargs(model, request)
        try:
            results = self._model.predict(str(request.source_path), **kwargs)
        except Exception as exc:
            if _is_out_of_memory(exc):
                self.unload()
                raise ProviderOutOfMemoryError(
                    f"{model.model_id} exhausted {self._device} memory; the model was unloaded"
                ) from exc
            raise ProviderLifecycleError(f"Ultralytics inference failed: {exc}") from exc
        cancellation.raise_if_cancelled()
        outputs, metadata = self._normalize_results(model, results, request.source_path)
        metadata.update(
            {
                "text_prompts": text_prompts,
                "prompt_provenance": dict(parameters),
                "checkpoint": str(model.checkpoint_path),
                "checkpoint_sha256": model.checkpoint_sha256,
                **text_encoder_provenance,
            }
        )
        return LifecycleInferenceResult(
            request_id=request.request_id,
            provider_id=model.provider_id,
            model_id=model.model_id,
            task=model.task,
            resolved_device=self._device,
            outputs=outputs,
            metadata=metadata,
        )

    def cancel(self, request_id: str) -> None:
        del request_id

    def unload(self) -> None:
        self._model = None
        self._model_id = None
        release_accelerator_memory()


class OriginalSamLifecycleProvider:
    provider_id = "segment_anything"

    def __init__(self) -> None:
        self._sam: Any | None = None
        self._device = "cpu"
        self._model_id: str | None = None

    def load(self, model: ProviderModelDefinition, device: str) -> None:
        self.unload()
        if not model.checkpoint_path.is_file():
            raise ProviderUnavailableError("The original SAM checkpoint is missing")
        try:
            from segment_anything import sam_model_registry
        except ImportError as exc:
            raise ProviderUnavailableError(f"segment_anything is unavailable: {exc}") from exc
        variant = str(model.metadata.get("sam_variant") or "vit_b")
        if variant not in sam_model_registry:
            raise ProviderUnavailableError(f"Unsupported original SAM architecture: {variant}")
        self._device = resolve_device(device)
        try:
            sam = sam_model_registry[variant](checkpoint=str(model.checkpoint_path))
            sam.to(device=self._device)
            sam.eval()
        except Exception as exc:
            if _is_out_of_memory(exc):
                self.unload()
                raise ProviderOutOfMemoryError(
                    "Original SAM exhausted device memory; the model was unloaded"
                ) from exc
            raise ProviderLifecycleError(f"Original SAM could not be loaded: {exc}") from exc
        self._sam = sam
        self._model_id = model.model_id

    def health_check(self) -> dict[str, Any]:
        if self._sam is None:
            raise ProviderUnavailableError("Original SAM is not loaded")
        return {
            "loaded": True,
            "model_id": self._model_id,
            "device": self._device,
            "segment_anything_version": _runtime_version("segment-anything"),
        }

    def infer(
        self,
        model: ProviderModelDefinition,
        request: LifecycleInferenceRequest,
        cancellation: CancellationToken,
    ) -> LifecycleInferenceResult:
        if self._sam is None or self._model_id != model.model_id:
            raise ProviderUnavailableError("The requested original SAM model is not loaded")
        cancellation.raise_if_cancelled()
        try:
            from segment_anything import SamPredictor
        except ImportError as exc:
            raise ProviderUnavailableError(f"segment_anything is unavailable: {exc}") from exc
        with Image.open(request.source_path) as source:
            rgb = np.asarray(source.convert("RGB"))
            width, height = source.size
        predictor = SamPredictor(self._sam)
        try:
            predictor.set_image(rgb)
            positive = list(request.parameters.get("positive_points") or [])
            negative = list(request.parameters.get("negative_points") or [])
            box = request.parameters.get("box")
            kwargs: dict[str, Any] = {
                "multimask_output": bool(request.parameters.get("multimask", True))
            }
            if positive or negative:
                kwargs["point_coords"] = np.asarray([*positive, *negative], dtype=np.float32)
                kwargs["point_labels"] = np.asarray(
                    [1] * len(positive) + [0] * len(negative), dtype=np.int32
                )
            if box is not None:
                kwargs["box"] = np.asarray(box, dtype=np.float32)
            if "point_coords" not in kwargs and "box" not in kwargs:
                raise ProviderLifecycleError("Original SAM requires a point or box prompt")
            masks, scores, logits = predictor.predict(**kwargs)
        except ProviderLifecycleError:
            raise
        except Exception as exc:
            if _is_out_of_memory(exc):
                self.unload()
                raise ProviderOutOfMemoryError(
                    "Original SAM exhausted device memory; the model was unloaded"
                ) from exc
            raise ProviderLifecycleError(f"Original SAM inference failed: {exc}") from exc
        cancellation.raise_if_cancelled()
        outputs: list[dict[str, Any]] = []
        for index, raw_mask in enumerate(masks):
            mask = _aligned_mask(raw_mask, width, height)
            if not mask.any():
                continue
            rows, columns = np.where(mask)
            outputs.append(
                {
                    "rank": 0,
                    "score": _safe_float(scores[index]),
                    "box": {
                        "x_min": float(columns.min()),
                        "y_min": float(rows.min()),
                        "x_max": float(columns.max() + 1),
                        "y_max": float(rows.max() + 1),
                    },
                    "raster_mask_png_base64": _mask_png(mask),
                    "mask_representation": "source_aligned_raster",
                    "source_width": width,
                    "source_height": height,
                    "logit_shape": list(np.asarray(logits[index]).shape),
                }
            )
        outputs.sort(key=lambda item: float(item["score"]), reverse=True)
        for rank, output in enumerate(outputs, start=1):
            output["rank"] = rank
        return LifecycleInferenceResult(
            request_id=request.request_id,
            provider_id=model.provider_id,
            model_id=model.model_id,
            task=model.task,
            resolved_device=self._device,
            outputs=outputs,
            metadata={
                "source_width": width,
                "source_height": height,
                "empty_result": not outputs,
                "prompt_provenance": dict(request.parameters),
                "checkpoint": str(model.checkpoint_path),
                "checkpoint_sha256": model.checkpoint_sha256,
                "scientific_validation": False,
            },
        )

    def cancel(self, request_id: str) -> None:
        del request_id

    def unload(self) -> None:
        self._sam = None
        self._model_id = None
        release_accelerator_memory()


class DepthAnythingLifecycleProvider:
    provider_id = "depth_anything_v2"

    def __init__(self) -> None:
        self._processor: Any | None = None
        self._model: Any | None = None
        self._device = "cpu"
        self._model_id: str | None = None

    def load(self, model: ProviderModelDefinition, device: str) -> None:
        self.unload()
        if not model.checkpoint_path.is_dir():
            raise ProviderUnavailableError("Depth Anything requires a local checkpoint folder")
        try:
            from transformers import AutoImageProcessor, AutoModelForDepthEstimation
        except ImportError as exc:
            raise ProviderUnavailableError(
                f"Transformers depth runtime is unavailable: {exc}"
            ) from exc
        self._device = resolve_device(device)
        try:
            processor = AutoImageProcessor.from_pretrained(  # type: ignore[no-untyped-call]
                str(model.checkpoint_path), local_files_only=True
            )
            runtime_model = AutoModelForDepthEstimation.from_pretrained(
                str(model.checkpoint_path), local_files_only=True
            )
            runtime_model.to(self._device)
            runtime_model.eval()
        except Exception as exc:
            if _is_out_of_memory(exc):
                self.unload()
                raise ProviderOutOfMemoryError(
                    "Depth Anything exhausted device memory; the model was unloaded"
                ) from exc
            raise ProviderLifecycleError(
                f"Depth Anything could not be loaded locally: {exc}"
            ) from exc
        self._processor = processor
        self._model = runtime_model
        self._model_id = model.model_id

    def health_check(self) -> dict[str, Any]:
        if self._model is None or self._processor is None:
            raise ProviderUnavailableError("Depth Anything is not loaded")
        config = getattr(self._model, "config", None)
        return {
            "loaded": True,
            "model_id": self._model_id,
            "device": self._device,
            "model_type": getattr(config, "model_type", None),
            "depth_estimation_type": getattr(config, "depth_estimation_type", None),
            "transformers_version": _runtime_version("transformers"),
        }

    def infer(
        self,
        model: ProviderModelDefinition,
        request: LifecycleInferenceRequest,
        cancellation: CancellationToken,
    ) -> LifecycleInferenceResult:
        if self._model is None or self._processor is None or self._model_id != model.model_id:
            raise ProviderUnavailableError("The requested Depth Anything model is not loaded")
        import torch
        import torch.nn.functional as functional

        cancellation.raise_if_cancelled()
        with Image.open(request.source_path) as source:
            image = source.convert("RGB")
            width, height = source.size
        try:
            inputs = self._processor(images=image, return_tensors="pt")
            inputs = {name: value.to(self._device) for name, value in inputs.items()}
            with torch.inference_mode():
                predicted = self._model(**inputs).predicted_depth
                aligned = functional.interpolate(
                    predicted.unsqueeze(1),
                    size=(height, width),
                    mode="bicubic",
                    align_corners=False,
                ).squeeze()
            raw = aligned.detach().float().cpu().numpy().astype(np.float32)
        except Exception as exc:
            if _is_out_of_memory(exc):
                self.unload()
                raise ProviderOutOfMemoryError(
                    "Depth Anything exhausted device memory; the model was unloaded"
                ) from exc
            raise ProviderLifecycleError(f"Depth Anything inference failed: {exc}") from exc
        cancellation.raise_if_cancelled()
        if raw.shape != (height, width) or not np.isfinite(raw).all():
            raise ProviderLifecycleError(
                "Depth Anything returned misaligned, NaN, or infinite relative-depth values"
            )
        minimum = float(raw.min())
        maximum = float(raw.max())
        display = np.zeros_like(raw, dtype=np.float32)
        if maximum > minimum:
            display = (raw - minimum) / (maximum - minimum)
        output = {
            "width": width,
            "height": height,
            "raw_min": minimum,
            "raw_max": maximum,
            "raw_mean": float(raw.mean()),
            "display_min": float(display.min()),
            "display_max": float(display.max()),
            "finite": True,
            "depth_kind": "relative",
        }
        return LifecycleInferenceResult(
            request_id=request.request_id,
            provider_id=model.provider_id,
            model_id=model.model_id,
            task=model.task,
            resolved_device=self._device,
            outputs=[output],
            metadata={
                "source_width": width,
                "source_height": height,
                "raw_output_preserved_separately": True,
                "display_normalization": "per_image_min_max",
                "physical_units": None,
                "relative_depth_only": True,
                "scientific_warning": (
                    "Relative depth is not physical coral height and has no centimeter or meter "
                    "units without an independent calibration."
                ),
                "checkpoint": str(model.checkpoint_path),
                "checkpoint_sha256": model.checkpoint_sha256,
                "preprocessing": getattr(self._processor, "to_dict", lambda: {})(),
            },
        )

    def cancel(self, request_id: str) -> None:
        del request_id

    def unload(self) -> None:
        self._processor = None
        self._model = None
        self._model_id = None
        release_accelerator_memory()


class UltralyticsEmbeddingLifecycleProvider(UltralyticsLifecycleProvider):
    provider_id = "ultralytics_embeddings"

    def infer(
        self,
        model: ProviderModelDefinition,
        request: LifecycleInferenceRequest,
        cancellation: CancellationToken,
    ) -> LifecycleInferenceResult:
        if self._model is None or self._model_id != model.model_id:
            raise ProviderUnavailableError("The requested embedding model is not loaded")
        cancellation.raise_if_cancelled()
        with Image.open(request.source_path) as source:
            image = source.convert("RGB")
            crop = request.parameters.get("crop")
            if crop is not None:
                image = image.crop(tuple(float(value) for value in crop))
            source_array = np.asarray(image)
        try:
            embeddings = self._model.embed(
                source_array,
                device=self._device,
                imgsz=int(request.parameters.get("imgsz", 224)),
                verbose=False,
            )
        except Exception as exc:
            if _is_out_of_memory(exc):
                self.unload()
                raise ProviderOutOfMemoryError(
                    "Embedding inference exhausted device memory; the model was unloaded"
                ) from exc
            raise ProviderLifecycleError(f"Embedding inference failed: {exc}") from exc
        cancellation.raise_if_cancelled()
        if not embeddings:
            raise ProviderLifecycleError("The embedding model returned no feature vector")
        value = embeddings[0]
        if hasattr(value, "detach"):
            vector = value.detach().float().cpu().numpy().reshape(-1).astype(np.float32)
        else:
            vector = np.asarray(value, dtype=np.float32).reshape(-1)
        if not np.isfinite(vector).all():
            raise ProviderLifecycleError("The embedding contains NaN or infinite values")
        norm = float(np.linalg.norm(vector))
        if norm <= 0:
            raise ProviderLifecycleError("The embedding is an all-zero vector")
        vector /= norm
        return LifecycleInferenceResult(
            request_id=request.request_id,
            provider_id=model.provider_id,
            model_id=model.model_id,
            task=model.task,
            resolved_device=self._device,
            outputs=[{"vector": vector.tolist(), "dimension": int(vector.size)}],
            metadata={
                "normalization": "l2",
                "preprocessing_version": "ultralytics-embed-imgsz224-rgb-v1",
                "feature_layer": "ultralytics_model_embed_default",
                "global_pooling": True,
                "crop": request.parameters.get("crop"),
                "checkpoint": str(model.checkpoint_path),
                "checkpoint_sha256": model.checkpoint_sha256,
            },
        )


ProviderFactory = Callable[[], LifecycleProvider]


class ProviderRuntimeManager:
    """Serialize accelerator use and keep at most one checkpoint resident."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._request_lock = threading.Lock()
        self._factories: dict[str, ProviderFactory] = {
            "ultralytics": UltralyticsLifecycleProvider,
            "ultralytics_sam": UltralyticsLifecycleProvider,
            "segment_anything": OriginalSamLifecycleProvider,
            "depth_anything_v2": DepthAnythingLifecycleProvider,
            "ultralytics_embeddings": UltralyticsEmbeddingLifecycleProvider,
        }
        self._provider: LifecycleProvider | None = None
        self._model: ProviderModelDefinition | None = None
        self._device: str | None = None
        self._state = ProviderState.UNLOADED
        self._failure_reason: str | None = None
        self._requests: dict[str, CancellationToken] = {}

    @property
    def state(self) -> ProviderState:
        return self._state

    @property
    def loaded_model_id(self) -> str | None:
        return self._model.model_id if self._model is not None else None

    @property
    def resolved_device(self) -> str | None:
        return self._device

    @property
    def failure_reason(self) -> str | None:
        return self._failure_reason

    def register_provider(self, provider_id: str, factory: ProviderFactory) -> None:
        with self._lock:
            self._factories[provider_id] = factory

    def load(self, model: ProviderModelDefinition, device: str) -> str:
        with self._lock:
            resolved = resolve_device(device)
            if (
                self._provider is not None
                and self._model is not None
                and self._model.model_id == model.model_id
                and self._device == resolved
                and self._state is ProviderState.LOADED
            ):
                return resolved
            self._unload_locked()
            factory = self._factories.get(model.provider_id)
            if factory is None:
                self._state = ProviderState.UNAVAILABLE
                self._failure_reason = f"No lifecycle adapter is registered for {model.provider_id}"
                raise ProviderUnavailableError(self._failure_reason)
            self._state = ProviderState.LOADING
            provider = factory()
            try:
                provider.load(model, resolved)
            except Exception as exc:
                provider.unload()
                release_accelerator_memory()
                self._state = ProviderState.FAILED
                self._failure_reason = str(exc)
                raise
            self._provider = provider
            self._model = model
            self._device = resolved
            self._state = ProviderState.LOADED
            self._failure_reason = None
            return resolved

    def health_check(self) -> dict[str, Any]:
        with self._lock:
            if self._provider is None:
                raise ProviderUnavailableError("No provider model is loaded")
            return self._provider.health_check()

    def infer(
        self,
        model: ProviderModelDefinition,
        request: LifecycleInferenceRequest,
    ) -> LifecycleInferenceResult:
        token = CancellationToken()
        with self._request_lock:
            if request.request_id in self._requests:
                raise ProviderLifecycleError(f"Duplicate active request id: {request.request_id}")
            self._requests[request.request_id] = token
        try:
            with self._lock:
                if self._provider is None or self._model is None:
                    raise ProviderUnavailableError("No provider model is loaded")
                if self._model.model_id != model.model_id:
                    raise ProviderUnavailableError(
                        "The requested model is no longer loaded; select and load it again"
                    )
                try:
                    result = self._provider.infer(model, request, token)
                except ProviderOutOfMemoryError:
                    self._unload_locked()
                    raise
                token.raise_if_cancelled()
                return result
        finally:
            with self._request_lock:
                self._requests.pop(request.request_id, None)

    def cancel(self, request_id: str) -> bool:
        with self._request_lock:
            token = self._requests.get(request_id)
            provider = self._provider
            if token is None:
                return False
            token.cancel()
        if provider is not None:
            provider.cancel(request_id)
        return True

    def unload(self) -> None:
        with self._lock:
            self._unload_locked()

    def _unload_locked(self) -> None:
        with self._request_lock:
            for token in self._requests.values():
                token.cancel()
        if self._provider is not None:
            try:
                self._provider.unload()
            finally:
                self._provider = None
        self._model = None
        self._device = None
        self._state = ProviderState.UNLOADED
        self._failure_reason = None
        release_accelerator_memory()

    def reopen_after_restart(self) -> None:
        """Normalize impossible persisted loaded/loading state after process restart."""

        self.unload()


__all__ = [
    "DepthAnythingLifecycleProvider",
    "OriginalSamLifecycleProvider",
    "ProviderRuntimeManager",
    "UltralyticsEmbeddingLifecycleProvider",
    "UltralyticsLifecycleProvider",
    "release_accelerator_memory",
]
