"""Local-only Transformers providers for Florence-2, Grounding DINO, and OWLv2."""

from __future__ import annotations

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


@dataclass(frozen=True)
class TransformersModelSpec:
    provider_name: str
    architecture: str
    task: str


def _require_model_directory(model_path: Path) -> Path:
    resolved = model_path.expanduser().resolve()
    if not resolved.is_dir():
        raise ValidationError(
            "Transformers providers require an existing local model directory. "
            "Automatic downloads are disabled during inference."
        )
    if not (resolved / "config.json").is_file():
        raise ValidationError("The selected Transformers model directory has no config.json")
    return resolved


def _model_type(model_path: Path) -> str:
    import json

    try:
        payload = json.loads((model_path / "config.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Could not read Transformers config.json: {exc}") from exc
    model_type = str(payload.get("model_type") or "").casefold().replace("-", "_")
    if model_type in {"grounding_dino", "owlv2", "florence2"}:
        return model_type
    architectures = " ".join(str(item) for item in payload.get("architectures", []))
    lowered = architectures.casefold()
    if "groundingdino" in lowered:
        return "grounding_dino"
    if "owlv2" in lowered:
        return "owlv2"
    if "florence2" in lowered:
        return "florence2"
    raise ValidationError(f"Unsupported Transformers vision architecture: {model_type or architectures}")


def inspect_transformers_model(model_path: Path) -> TransformersModelSpec:
    model_dir = _require_model_directory(model_path)
    provider = _model_type(model_dir)
    task = "phrase_grounding" if provider == "florence2" else "open_vocabulary_detect"
    return TransformersModelSpec(provider_name=provider, architecture=provider, task=task)


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
        spec = inspect_transformers_model(model_path)
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
                "model_directory": str(model_path.resolve()),
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
        except Exception as exc:
            raise ValidationError(
                "The Transformers provider pack is not installed. Install transformers, "
                f"accelerate, safetensors, and huggingface_hub: {exc}"
            ) from exc

        resolved_device = resolve_torch_device(device)
        torch_device = torch.device("cuda:0" if resolved_device == 0 else "cpu")
        dtype = torch.float16 if torch_device.type == "cuda" else torch.float32
        try:
            self._processor = AutoProcessor.from_pretrained(
                model_dir,
                local_files_only=True,
                trust_remote_code=self.provider_name == "florence2",
            )
            model_class = (
                AutoModelForCausalLM
                if self.provider_name == "florence2"
                else AutoModelForZeroShotObjectDetection
            )
            self._model = model_class.from_pretrained(
                model_dir,
                local_files_only=True,
                trust_remote_code=self.provider_name == "florence2",
                torch_dtype=dtype,
            ).to(torch_device)
            self._model.eval()
        except Exception as exc:
            self.unload_model()
            raise ValidationError(f"Could not load local {self.provider_name} model: {exc}") from exc
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
        prompt = (text_prompt or "").strip()
        if not prompt:
            raise ValidationError(
                f"{self.provider_name} requires a text prompt for open-vocabulary detection"
            )
        image = Image.open(image_path).convert("RGB")
        if self.provider_name == "florence2":
            return self._predict_florence(image, prompt, settings)
        return self._predict_zero_shot(image, prompt, settings)

    def _predict_zero_shot(
        self,
        image: Image.Image,
        prompt: str,
        settings: DetectionSettings,
    ) -> list[DetectionPrediction]:
        import torch

        labels = [item.strip() for item in prompt.split(",") if item.strip()]
        if not labels:
            labels = [prompt]
        text: Any = [labels] if self.provider_name == "owlv2" else labels
        inputs = self._processor(images=image, text=text, return_tensors="pt")
        inputs = {key: value.to(self._device) for key, value in inputs.items()}
        with torch.inference_mode():
            outputs = self._model(**inputs)
        target_sizes = torch.tensor([image.size[::-1]], device=self._device)
        processed = self._processor.post_process_grounded_object_detection(
            outputs,
            target_sizes=target_sizes,
            threshold=settings.confidence_threshold,
            text_threshold=settings.confidence_threshold,
        )[0]
        boxes = processed.get("boxes", [])
        scores = processed.get("scores", [])
        result_labels = processed.get("text_labels", processed.get("labels", []))
        predictions: list[DetectionPrediction] = []
        for index, (box, score) in enumerate(zip(boxes, scores, strict=False)):
            values = [float(value) for value in box.detach().cpu().tolist()]
            label_value = result_labels[index] if index < len(result_labels) else "object"
            if hasattr(label_value, "item"):
                class_index = int(label_value.item())
                label = labels[class_index] if 0 <= class_index < len(labels) else str(class_index)
            else:
                class_index = labels.index(str(label_value)) if str(label_value) in labels else None
                label = str(label_value)
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
        settings: DetectionSettings,
    ) -> list[DetectionPrediction]:
        import torch

        task_prompt = f"<OPEN_VOCABULARY_DETECTION>{prompt}"
        inputs = self._processor(text=task_prompt, images=image, return_tensors="pt")
        inputs = {key: value.to(self._device) for key, value in inputs.items()}
        with torch.inference_mode():
            generated = self._model.generate(
                **inputs,
                max_new_tokens=1024,
                do_sample=False,
                num_beams=3,
            )
        generated_text = self._processor.batch_decode(generated, skip_special_tokens=False)[0]
        parsed = self._processor.post_process_generation(
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
                    confidence=max(settings.confidence_threshold, 1.0),
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
