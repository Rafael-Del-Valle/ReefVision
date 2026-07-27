"""Local-only Transformers providers for Florence-2, Grounding DINO, and OWLv2."""

from __future__ import annotations

import json
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from reefvision.domain.errors import ValidationError
from reefvision.ml.providers import (
    DetectionModelMetadata,
    DetectionPrediction,
    DetectionSettings,
    PixelBox,
    resolve_torch_device,
)

_SUPPORTED = {"grounding_dino", "owlv2", "florence2"}
_POINTER_FORMAT = "reefvision_transformers_model_pointer_v1"
_CURRENT_TEXT_PROMPT: ContextVar[str | None] = ContextVar(
    "reefvision_transformers_text_prompt",
    default=None,
)


@dataclass(frozen=True)
class TransformersModelSpec:
    provider_name: str
    architecture: str
    task: str


def set_transformers_text_prompt(prompt: str | None) -> Token[str | None]:
    normalized = prompt.strip() if isinstance(prompt, str) else None
    return _CURRENT_TEXT_PROMPT.set(normalized or None)


def reset_transformers_text_prompt(token: Token[str | None]) -> None:
    _CURRENT_TEXT_PROMPT.reset(token)


def current_transformers_text_prompt() -> str | None:
    return _CURRENT_TEXT_PROMPT.get()


def _safe_catalog_id(value: object) -> str:
    catalog_id = str(value or "").strip()
    segments = catalog_id.split("/")
    if not segments or any(
        not segment or segment in {".", ".."} or Path(segment).name != segment
        for segment in segments
    ):
        raise ValidationError("The Transformers model pointer has an unsafe catalog id")
    return catalog_id


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Could not read {label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValidationError(f"{label} must contain a JSON object")
    return payload


def _pointer_model_directory(pointer_path: Path) -> Path:
    pointer = _read_json_object(pointer_path, label="Transformers model pointer")
    if pointer.get("format") != _POINTER_FORMAT:
        raise ValidationError("The selected JSON file is not a ReefVision model pointer")
    catalog_id = _safe_catalog_id(pointer.get("catalog_id"))
    provider_id = str(pointer.get("provider_id") or "").casefold().replace("-", "_")
    if provider_id not in _SUPPORTED:
        raise ValidationError("The Transformers model pointer provider is unsupported")
    snapshot_sha256 = str(pointer.get("snapshot_sha256") or "").casefold()
    if len(snapshot_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in snapshot_sha256
    ):
        raise ValidationError("The Transformers model pointer has no valid snapshot checksum")
    model_dir = Path(str(pointer.get("model_path") or "")).expanduser().resolve()
    expected_tail = Path(
        "models",
        "provider-packs",
        "transformers-vision",
        *catalog_id.split("/"),
    )
    actual_tail = tuple(part.casefold() for part in model_dir.parts[-len(expected_tail.parts) :])
    required_tail = tuple(part.casefold() for part in expected_tail.parts)
    if actual_tail != required_tail:
        raise ValidationError(
            "The Transformers model pointer does not target managed provider-pack storage"
        )
    index_root = model_dir.parents[len(catalog_id.split("/")) - 1]
    index = index_root / "manifest.json"
    manifest = _read_json_object(index, label="managed Transformers model index")
    models = manifest.get("models")
    record = models.get(catalog_id) if isinstance(models, dict) else None
    if not isinstance(record, dict) or record.get("verified") is not True:
        raise ValidationError(
            "The Transformers model pointer is not present in the verified model index"
        )
    if Path(str(record.get("path") or "")).resolve() != model_dir:
        raise ValidationError("The Transformers model index path does not match the pointer")
    if str(record.get("snapshot_sha256") or "").casefold() != snapshot_sha256:
        raise ValidationError(
            "The Transformers model pointer checksum does not match the verified index"
        )
    revision = str(pointer.get("resolved_revision") or "")
    if str(record.get("resolved_revision") or "") != revision:
        raise ValidationError(
            "The Transformers model pointer revision does not match the verified index"
        )
    marker = model_dir / ".reefvision-revision"
    try:
        marker_revision = marker.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValidationError(
            "The Transformers model revision marker is missing or unreadable"
        ) from exc
    if marker_revision != revision:
        raise ValidationError("The Transformers model revision marker is invalid")
    return model_dir


def _require_model_directory(model_path: Path) -> Path:
    resolved = model_path.expanduser().resolve()
    if resolved.is_file() and resolved.suffix.casefold() == ".json":
        resolved = _pointer_model_directory(resolved)
    if not resolved.is_dir():
        raise ValidationError(
            "Transformers providers require an existing local model directory or verified "
            "ReefVision model pointer. Automatic downloads are disabled during inference."
        )
    if not (resolved / "config.json").is_file():
        raise ValidationError("The selected Transformers model directory has no config.json")
    return resolved


def _model_type(model_path: Path) -> str:
    try:
        payload = json.loads((model_path / "config.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Could not read Transformers config.json: {exc}") from exc
    model_type = str(payload.get("model_type") or "").casefold().replace("-", "_")
    if model_type in _SUPPORTED:
        return model_type
    architectures = " ".join(str(item) for item in payload.get("architectures", []))
    lowered = architectures.casefold()
    if "groundingdino" in lowered:
        return "grounding_dino"
    if "owlv2" in lowered:
        return "owlv2"
    if "florence2" in lowered:
        return "florence2"
    raise ValidationError(
        f"Unsupported Transformers vision architecture: {model_type or architectures}"
    )


def inspect_transformers_model(model_path: Path) -> TransformersModelSpec:
    model_dir = _require_model_directory(model_path)
    provider = _model_type(model_dir)
    task = "phrase_grounding" if provider == "florence2" else "open_vocabulary_detect"
    return TransformersModelSpec(
        provider_name=provider,
        architecture=provider,
        task=task,
    )


class TransformersVisionDetectionProvider:
    """One adapter for the three supported local Transformers model families."""

    provider_version = "1.0"

    def __init__(self, provider_name: str) -> None:
        normalized = provider_name.strip().casefold().replace("-", "_")
        if normalized not in _SUPPORTED:
            raise ValidationError(f"Unsupported Transformers provider: {provider_name}")
        self.provider_name = normalized
        self._processor: Any | None = None
        self._model: Any | None = None
        self._device: Any = "cpu"
        self._model_dir: Path | None = None

    def inspect_model(self, model_path: Path) -> DetectionModelMetadata:
        model_dir = _require_model_directory(model_path)
        spec = inspect_transformers_model(model_dir)
        if spec.provider_name != self.provider_name:
            raise ValidationError(
                f"The selected model is {spec.provider_name}, not {self.provider_name}"
            )
        return DetectionModelMetadata(
            framework="transformers",
            task=spec.task,
            provider_name=self.provider_name,
            provider_version=self.provider_version,
            class_labels=[],
            input_size=None,
            metadata={
                "local_files_only": True,
                "model_directory": str(model_dir),
                "prompt_required": True,
                "architecture": spec.architecture,
            },
        )

    def load_model(self, model_path: Path, device: str) -> None:
        model_dir = _require_model_directory(model_path)
        spec = inspect_transformers_model(model_dir)
        if spec.provider_name != self.provider_name:
            raise ValidationError(
                f"The selected model is {spec.provider_name}, not {self.provider_name}"
            )
        try:
            import torch
            from transformers import (
                AutoModelForCausalLM,
                AutoModelForZeroShotObjectDetection,
                AutoProcessor,
            )

            image_text_model_class: Any | None = None
            try:
                from transformers import AutoModelForImageTextToText

                image_text_model_class = AutoModelForImageTextToText
            except ImportError:
                pass
        except Exception as exc:
            raise ValidationError(
                "The Transformers provider pack is not installed. Install transformers, "
                f"accelerate, safetensors, and huggingface_hub: {exc}"
            ) from exc

        resolved_device = resolve_torch_device(device)
        torch_device = torch.device("cuda:0" if resolved_device == 0 else "cpu")
        dtype = torch.float16 if torch_device.type == "cuda" else torch.float32
        try:
            auto_processor: Any = AutoProcessor
            self._processor = auto_processor.from_pretrained(
                model_dir,
                local_files_only=True,
                trust_remote_code=self.provider_name == "florence2",
            )
            model_class: Any
            if self.provider_name == "florence2":
                model_class = image_text_model_class or AutoModelForCausalLM
            else:
                model_class = AutoModelForZeroShotObjectDetection
            self._model = model_class.from_pretrained(
                model_dir,
                local_files_only=True,
                trust_remote_code=self.provider_name == "florence2",
                torch_dtype=dtype,
            ).to(torch_device)
            self._model.eval()
        except Exception as exc:
            self.unload_model()
            raise ValidationError(
                f"Could not load local {self.provider_name} model: {exc}"
            ) from exc
        self._device = torch_device
        self._model_dir = model_dir

    def predict(
        self,
        image_path: Path,
        settings: DetectionSettings,
        *,
        text_prompt: str | None = None,
    ) -> list[DetectionPrediction]:
        if self._model is None or self._processor is None:
            raise ValidationError("The Transformers model is not loaded")
        if not image_path.is_file():
            raise ValidationError("Transformers inference requires an existing local image")
        prompt = (text_prompt or current_transformers_text_prompt() or "").strip()
        if not prompt:
            raise ValidationError(
                f"{self.provider_name} requires a text prompt for open-vocabulary detection"
            )
        with Image.open(image_path) as source:
            image = source.convert("RGB")
        if self.provider_name == "florence2":
            return self._predict_florence(image, prompt)
        return self._predict_zero_shot(image, prompt, settings)

    def _predict_zero_shot(
        self,
        image: Image.Image,
        prompt: str,
        settings: DetectionSettings,
    ) -> list[DetectionPrediction]:
        import torch

        processor = self._processor
        model = self._model
        if processor is None or model is None:
            raise ValidationError("The Transformers model is not loaded")
        labels = [item.strip() for item in prompt.split(",") if item.strip()]
        if not labels:
            labels = [prompt]
        text_labels = [labels]
        inputs = processor(
            images=image,
            text=text_labels,
            return_tensors="pt",
        )
        inputs = {key: value.to(self._device) for key, value in inputs.items()}
        with torch.inference_mode():
            outputs = model(**inputs)
        target_sizes = torch.tensor([image.size[::-1]], device=self._device)
        if self.provider_name == "grounding_dino":
            processed = processor.post_process_grounded_object_detection(
                outputs=outputs,
                input_ids=inputs.get("input_ids"),
                threshold=settings.confidence_threshold,
                text_threshold=settings.confidence_threshold,
                target_sizes=target_sizes,
                text_labels=text_labels,
            )[0]
        else:
            post_process = getattr(
                processor,
                "post_process_grounded_object_detection",
                None,
            ) or getattr(processor, "post_process_object_detection", None)
            if post_process is None:
                raise ValidationError("OWLv2 processor has no supported detection postprocessor")
            try:
                processed = post_process(
                    outputs=outputs,
                    threshold=settings.confidence_threshold,
                    target_sizes=target_sizes,
                    text_labels=text_labels,
                )[0]
            except TypeError:
                processed = post_process(
                    outputs=outputs,
                    threshold=settings.confidence_threshold,
                    target_sizes=target_sizes,
                )[0]
        boxes = processed.get("boxes", [])
        scores = processed.get("scores", [])
        result_labels = processed.get(
            "text_labels",
            processed.get("labels", []),
        )
        predictions: list[DetectionPrediction] = []
        for index, (box, score) in enumerate(zip(boxes, scores, strict=False)):
            values = [float(value) for value in box.detach().cpu().tolist()]
            if len(values) != 4:
                continue
            label_value = result_labels[index] if index < len(result_labels) else "object"
            class_index: int | None
            if hasattr(label_value, "item"):
                class_index = int(label_value.item())
                label = labels[class_index] if 0 <= class_index < len(labels) else str(class_index)
            else:
                label = str(label_value)
                class_index = labels.index(label) if label in labels else None
            predictions.append(
                DetectionPrediction(
                    label=label,
                    class_index=class_index,
                    confidence=float(score.detach().cpu().item()),
                    box=PixelBox(*values),
                )
            )
        return predictions

    def _predict_florence(
        self,
        image: Image.Image,
        prompt: str,
    ) -> list[DetectionPrediction]:
        import torch

        processor = self._processor
        model = self._model
        if processor is None or model is None:
            raise ValidationError("The Transformers model is not loaded")
        task_prompt = f"<OPEN_VOCABULARY_DETECTION>{prompt}"
        inputs = processor(
            text=task_prompt,
            images=image,
            return_tensors="pt",
        )
        inputs = {key: value.to(self._device) for key, value in inputs.items()}
        with torch.inference_mode():
            generated = model.generate(
                **inputs,
                max_new_tokens=1024,
                do_sample=False,
                num_beams=3,
            )
        generated_text = processor.batch_decode(
            generated,
            skip_special_tokens=False,
        )[0]
        parsed = processor.post_process_generation(
            generated_text,
            task="<OPEN_VOCABULARY_DETECTION>",
            image_size=image.size,
        )
        payload = parsed.get("<OPEN_VOCABULARY_DETECTION>", parsed)
        boxes = payload.get("bboxes", payload.get("boxes", []))
        labels = payload.get("bboxes_labels", payload.get("labels", []))
        predictions: list[DetectionPrediction] = []
        for index, box in enumerate(boxes):
            values = [float(value) for value in box]
            if len(values) != 4:
                continue
            label = str(labels[index]) if index < len(labels) else prompt
            predictions.append(
                DetectionPrediction(
                    label=label,
                    class_index=None,
                    confidence=1.0,
                    box=PixelBox(*values),
                )
            )
        return predictions

    def unload_model(self) -> None:
        self._processor = None
        self._model = None
        self._model_dir = None
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            return
