"""Offline Transformers vision providers for prompt-driven ReefVision detection."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from PIL import Image, UnidentifiedImageError

from reefvision.domain.errors import ValidationError
from reefvision.ml.providers import (
    DetectionPrediction,
    DetectionSettings,
    PixelBox,
    ensure_finite_box,
    resolve_torch_device,
)

TRANSFORMERS_BUNDLE_METADATA = "reefvision-transformers-model.json"
SUPPORTED_TRANSFORMERS_PROVIDERS = frozenset({"florence2", "grounding_dino", "owlv2"})
_MAX_ARCHIVE_FILES = 20_000
_MAX_ARCHIVE_BYTES = 12 * 1024**3


@dataclass(frozen=True)
class TransformersBundleMetadata:
    provider_id: str
    repo_id: str
    revision: str
    model_family: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_archive_member(info: zipfile.ZipInfo) -> PurePosixPath:
    path = PurePosixPath(info.filename)
    if (
        not info.filename
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or "\\" in info.filename
    ):
        raise ValidationError("Transformers model bundle contains an unsafe path")
    unix_mode = (info.external_attr >> 16) & 0o170000
    if unix_mode == 0o120000:
        raise ValidationError("Transformers model bundle cannot contain symbolic links")
    return path


def inspect_transformers_bundle(bundle_path: Path) -> TransformersBundleMetadata:
    if not bundle_path.is_file() or bundle_path.suffix.casefold() != ".zip":
        raise ValidationError("Transformers providers require a managed ReefVision .zip bundle")
    try:
        with zipfile.ZipFile(bundle_path) as archive:
            infos = archive.infolist()
            if not infos or len(infos) > _MAX_ARCHIVE_FILES:
                raise ValidationError("Transformers model bundle has an invalid file count")
            total_size = 0
            names: set[str] = set()
            for info in infos:
                member = _safe_archive_member(info)
                total_size += int(info.file_size)
                if total_size > _MAX_ARCHIVE_BYTES:
                    raise ValidationError("Transformers model bundle exceeds the extraction limit")
                names.add(member.as_posix())
            try:
                payload = json.loads(archive.read(TRANSFORMERS_BUNDLE_METADATA).decode("utf-8"))
            except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValidationError("Transformers model bundle metadata is invalid") from exc
    except zipfile.BadZipFile as exc:
        raise ValidationError("Transformers model bundle is not a valid ZIP archive") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("format") != "reefvision_transformers_snapshot_v1"
    ):
        raise ValidationError("The selected ZIP is not a ReefVision Transformers model bundle")
    provider_id = str(payload.get("provider_id") or "").strip().casefold()
    if provider_id not in SUPPORTED_TRANSFORMERS_PROVIDERS:
        raise ValidationError("Transformers model bundle provider is unsupported")
    repo_id = str(payload.get("repo_id") or "").strip()
    revision = str(payload.get("revision") or "").strip()
    family = str(payload.get("model_family") or "").strip()
    if not repo_id or not revision or not family:
        raise ValidationError("Transformers model bundle provenance is incomplete")
    if "config.json" not in names or not any(name.endswith(".safetensors") for name in names):
        raise ValidationError("Transformers model bundle is missing config or safetensors weights")
    return TransformersBundleMetadata(
        provider_id=provider_id,
        repo_id=repo_id,
        revision=revision,
        model_family=family,
    )


def _extract_bundle(bundle_path: Path, cache_root: Path) -> tuple[Path, TransformersBundleMetadata]:
    metadata = inspect_transformers_bundle(bundle_path)
    checksum = _sha256(bundle_path)
    destination = cache_root / checksum
    ready_marker = destination / ".reefvision-ready"
    if ready_marker.is_file():
        return destination, metadata

    cache_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f"{checksum[:12]}-", dir=cache_root))
    try:
        with zipfile.ZipFile(bundle_path) as archive:
            for info in archive.infolist():
                member = _safe_archive_member(info)
                target = temporary.joinpath(*member.parts)
                resolved = target.resolve(strict=False)
                if temporary.resolve() not in resolved.parents and resolved != temporary.resolve():
                    raise ValidationError(
                        "Transformers model extraction escaped its cache directory"
                    )
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
        (temporary / ".reefvision-ready").write_text(checksum + "\n", encoding="utf-8")
        try:
            os.replace(temporary, destination)
        except OSError:
            if not ready_marker.is_file():
                raise
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
    return destination, metadata


def _torch_device(requested: str) -> Any:
    resolved = resolve_torch_device(requested)
    if resolved == 0:
        return "cuda:0"
    return resolved


def _finite_prediction(
    *,
    label: str,
    confidence: float,
    coordinates: Any,
    image_width: int,
    image_height: int,
) -> DetectionPrediction | None:
    try:
        raw = list(coordinates)
        if len(raw) != 4:
            return None
        x_min = max(0.0, min(float(raw[0]), float(image_width)))
        y_min = max(0.0, min(float(raw[1]), float(image_height)))
        x_max = max(0.0, min(float(raw[2]), float(image_width)))
        y_max = max(0.0, min(float(raw[3]), float(image_height)))
        score = float(confidence)
    except (TypeError, ValueError, OverflowError):
        return None
    box = PixelBox(x_min=x_min, y_min=y_min, x_max=x_max, y_max=y_max)
    try:
        ensure_finite_box(box)
    except ValidationError:
        return None
    return DetectionPrediction(
        label=(label.strip() or "object")[:200],
        class_index=None,
        confidence=max(0.0, min(score, 1.0)),
        box=box,
    )


def _result_values(result: Any, key: str) -> list[Any]:
    value = result.get(key, []) if isinstance(result, dict) else getattr(result, key, [])
    if hasattr(value, "detach"):
        value = value.detach().cpu().tolist()
    elif hasattr(value, "tolist"):
        value = value.tolist()
    return list(value or [])


class TransformersVisionProvider:
    """Load one verified local HF snapshot and return reviewable prompt detections."""

    provider_version = "1.0.0"

    def __init__(self, provider_id: str, *, cache_root: Path) -> None:
        normalized = provider_id.strip().casefold()
        if normalized not in SUPPORTED_TRANSFORMERS_PROVIDERS:
            raise ValidationError(f"Unsupported Transformers vision provider: {provider_id}")
        self.provider_id = normalized
        self.provider_name = normalized
        self.cache_root = cache_root
        self._processor: Any | None = None
        self._model: Any | None = None
        self._device: Any = "cpu"
        self._metadata: TransformersBundleMetadata | None = None

    def inspect_model(self, bundle_path: Path) -> TransformersBundleMetadata:
        metadata = inspect_transformers_bundle(bundle_path)
        if metadata.provider_id != self.provider_id:
            raise ValidationError(
                f"Expected a {self.provider_id} bundle but received {metadata.provider_id}"
            )
        return metadata

    def load_model(self, bundle_path: Path, device: str) -> None:
        metadata = self.inspect_model(bundle_path)
        snapshot, _ = _extract_bundle(bundle_path, self.cache_root)
        try:
            import torch
            from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor
        except Exception as exc:  # pragma: no cover - depends on packaged provider stack
            raise ValidationError(
                f"Transformers vision dependencies are unavailable: {exc}"
            ) from exc

        self._device = _torch_device(device)
        try:
            self._processor = AutoProcessor.from_pretrained(
                snapshot,
                local_files_only=True,
                trust_remote_code=False,
            )
            if self.provider_id == "florence2":
                from transformers import Florence2ForConditionalGeneration

                self._model = Florence2ForConditionalGeneration.from_pretrained(
                    snapshot,
                    local_files_only=True,
                    trust_remote_code=False,
                    torch_dtype=torch.float16
                    if str(self._device).startswith("cuda")
                    else torch.float32,
                )
            else:
                self._model = AutoModelForZeroShotObjectDetection.from_pretrained(
                    snapshot,
                    local_files_only=True,
                    trust_remote_code=False,
                    torch_dtype=torch.float16
                    if str(self._device).startswith("cuda")
                    else torch.float32,
                )
            self._model.to(self._device)
            self._model.eval()
            self._metadata = metadata
        except Exception as exc:  # pragma: no cover - depends on third-party model files
            self.unload_model()
            raise ValidationError(
                f"{self.provider_id} could not load the local snapshot: {exc}"
            ) from exc

    def predict(
        self,
        image_path: Path,
        text_prompts: list[str],
        settings: DetectionSettings,
    ) -> list[DetectionPrediction]:
        if self._processor is None or self._model is None or self._metadata is None:
            raise ValidationError("The Transformers vision model is not loaded")
        prompts = [value.strip() for value in text_prompts if value.strip()]
        if not prompts:
            raise ValidationError("Prompt inference requires at least one text label")
        try:
            with Image.open(image_path) as source:
                source.load()
                image = source.convert("RGB")
        except (OSError, UnidentifiedImageError) as exc:
            raise ValidationError("Prompt inference source image is unreadable") from exc
        if self.provider_id == "florence2":
            return self._predict_florence(image, prompts, settings)
        return self._predict_grounded(image, prompts, settings)

    def _predict_grounded(
        self,
        image: Image.Image,
        prompts: list[str],
        settings: DetectionSettings,
    ) -> list[DetectionPrediction]:
        try:
            import torch

            text: Any
            if self.provider_id == "grounding_dino":
                text = ". ".join(prompt.rstrip(".") for prompt in prompts) + "."
            else:
                text = [prompts]
            inputs = self._processor(images=image, text=text, return_tensors="pt")
            inputs = {
                key: value.to(self._device) if hasattr(value, "to") else value
                for key, value in inputs.items()
            }
            with torch.inference_mode():
                outputs = self._model(**inputs)
            postprocess = getattr(
                self._processor,
                "post_process_grounded_object_detection",
                None,
            )
            if postprocess is None:
                raise ValidationError("The installed processor cannot decode grounded detections")
            kwargs: dict[str, Any] = {
                "target_sizes": [(image.height, image.width)],
                "threshold": settings.confidence_threshold,
            }
            if self.provider_id == "grounding_dino":
                kwargs["input_ids"] = inputs.get("input_ids")
                kwargs["text_threshold"] = settings.confidence_threshold
            decoded = postprocess(outputs, **kwargs)
            result = decoded[0] if decoded else {}
        except ValidationError:
            raise
        except Exception as exc:  # pragma: no cover - third-party runtime
            raise ValidationError(f"{self.provider_id} prompt inference failed: {exc}") from exc

        boxes = _result_values(result, "boxes")
        scores = _result_values(result, "scores")
        labels = _result_values(result, "text_labels") or _result_values(result, "labels")
        predictions: list[DetectionPrediction] = []
        for index, box in enumerate(boxes):
            label_value = labels[index] if index < len(labels) else "object"
            if isinstance(label_value, int) and 0 <= label_value < len(prompts):
                label_value = prompts[label_value]
            score = scores[index] if index < len(scores) else 1.0
            prediction = _finite_prediction(
                label=str(label_value),
                confidence=float(score),
                coordinates=box,
                image_width=image.width,
                image_height=image.height,
            )
            if prediction is not None and prediction.confidence >= settings.confidence_threshold:
                predictions.append(prediction)
        return predictions

    def _predict_florence(
        self,
        image: Image.Image,
        prompts: list[str],
        settings: DetectionSettings,
    ) -> list[DetectionPrediction]:
        task = "<OPEN_VOCABULARY_DETECTION>"
        prompt = task + ", ".join(prompts)
        try:
            import torch

            inputs = self._processor(text=prompt, images=image, return_tensors="pt")
            inputs = {
                key: value.to(self._device) if hasattr(value, "to") else value
                for key, value in inputs.items()
            }
            with torch.inference_mode():
                generated_ids = self._model.generate(
                    **inputs,
                    max_new_tokens=1024,
                    num_beams=3,
                    do_sample=False,
                )
            generated_text = self._processor.batch_decode(
                generated_ids,
                skip_special_tokens=False,
            )[0]
            decoded = self._processor.post_process_generation(
                generated_text,
                task=task,
                image_size=(image.width, image.height),
            )
            result = decoded.get(task, decoded) if isinstance(decoded, dict) else {}
        except Exception as exc:  # pragma: no cover - third-party runtime
            raise ValidationError(f"Florence-2 prompt inference failed: {exc}") from exc

        boxes = _result_values(result, "bboxes") or _result_values(result, "boxes")
        labels = (
            _result_values(result, "bboxes_labels")
            or _result_values(result, "labels")
            or _result_values(result, "text_labels")
        )
        predictions: list[DetectionPrediction] = []
        for index, box in enumerate(boxes):
            label = str(labels[index]) if index < len(labels) else "object"
            prediction = _finite_prediction(
                label=label,
                confidence=1.0,
                coordinates=box,
                image_width=image.width,
                image_height=image.height,
            )
            if prediction is not None:
                predictions.append(prediction)
        return predictions

    def unload_model(self) -> None:
        self._processor = None
        self._model = None
        self._metadata = None
        try:  # pragma: no cover - depends on CUDA availability
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            return
