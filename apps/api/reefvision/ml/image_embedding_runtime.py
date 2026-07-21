"""Automatic image-embedding providers for active learning."""

from __future__ import annotations

import gc
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from PIL import Image

from reefvision.domain.errors import ValidationError
from reefvision.ml.provider_verification import resolve_device

ULTRALYTICS_EMBEDDING_PREPROCESSING_VERSION = "ultralytics-rgb-imgsz224-embed-v1"


class EmbeddingProvider(Protocol):
    provider_id: str
    model_id: str
    model_version: str
    checkpoint_checksum: str | None
    preprocessing_version: str

    def load(self, device: str) -> str: ...

    def embed_batch(
        self,
        inputs: list[tuple[Path, tuple[float, float, float, float] | None]],
    ) -> list[tuple[list[float], dict[str, Any]]]: ...

    def unload(self) -> None: ...


def _read_embedding_input(
    path: Path,
    crop: tuple[float, float, float, float] | None,
) -> np.ndarray[Any, Any]:
    if not path.is_file():
        raise ValidationError("The managed source image is missing")
    try:
        with Image.open(path) as source:
            source.load()
            image = source.convert("RGB")
            if crop is not None:
                x_min, y_min, x_max, y_max = crop
                if not (x_max > x_min and y_max > y_min):
                    raise ValidationError("Embedding crop must have positive width and height")
                if x_min < 0 or y_min < 0 or x_max > image.width or y_max > image.height:
                    raise ValidationError("Embedding crop must remain inside the source image")
                image = image.crop(crop)
            return np.asarray(image)
    except OSError as exc:
        raise ValidationError("The managed source image could not be read") from exc


class UltralyticsBackboneEmbeddingProvider:
    """Pool the deterministic feature vector exposed by a local Ultralytics backbone."""

    provider_id = "ultralytics_backbone"
    preprocessing_version = ULTRALYTICS_EMBEDDING_PREPROCESSING_VERSION

    def __init__(
        self,
        *,
        model_id: str,
        model_version: str,
        checkpoint_path: Path,
        checkpoint_checksum: str,
    ) -> None:
        self.model_id = model_id
        self.model_version = model_version
        self.checkpoint_path = checkpoint_path
        self.checkpoint_checksum = checkpoint_checksum
        self._model: Any | None = None
        self._device = "cpu"

    def load(self, device: str) -> str:
        if not self.checkpoint_path.is_file():
            raise ValidationError(
                "The local embedding checkpoint is missing; automatic downloads are disabled"
            )
        self._device = resolve_device(device)
        try:
            ultralytics: Any = import_module("ultralytics")
        except ImportError as exc:
            raise ValidationError("Ultralytics is unavailable for embedding generation") from exc
        self._model = ultralytics.YOLO(str(self.checkpoint_path))
        return self._device

    def embed_batch(
        self,
        inputs: list[tuple[Path, tuple[float, float, float, float] | None]],
    ) -> list[tuple[list[float], dict[str, Any]]]:
        if self._model is None:
            raise ValidationError("The embedding provider is not loaded")
        if not inputs:
            return []
        source_arrays = [_read_embedding_input(path, crop) for path, crop in inputs]
        try:
            outputs = self._model.embed(
                source_arrays,
                imgsz=224,
                device=self._device,
                verbose=False,
            )
        except Exception as exc:
            if "out of memory" in str(exc).casefold():
                self.unload()
                raise ValidationError(
                    "Embedding generation exhausted device memory; the model was unloaded"
                ) from exc
            raise ValidationError(f"Ultralytics embedding generation failed: {exc}") from exc
        if len(outputs) != len(inputs):
            raise ValidationError("The embedding provider returned an unexpected batch size")
        results: list[tuple[list[float], dict[str, Any]]] = []
        for output, (path, crop) in zip(outputs, inputs, strict=True):
            if hasattr(output, "detach"):
                vector = output.detach().float().cpu().numpy().reshape(-1).astype(np.float32)
            else:
                vector = np.asarray(output, dtype=np.float32).reshape(-1)
            if not np.isfinite(vector).all():
                raise ValidationError("The embedding provider returned NaN or infinite values")
            norm = float(np.linalg.norm(vector))
            if norm <= 0:
                raise ValidationError("The embedding provider returned an all-zero vector")
            vector /= norm
            results.append(
                (
                    vector.tolist(),
                    {
                        "runtime": "ultralytics.YOLO.embed",
                        "provider_id": self.provider_id,
                        "model_id": self.model_id,
                        "model_version": self.model_version,
                        "checkpoint_sha256": self.checkpoint_checksum,
                        "resolved_device": self._device,
                        "preprocessing_version": self.preprocessing_version,
                        "input_color_space": "RGB",
                        "input_size": [224, 224],
                        "feature_layer": "ultralytics_default_embed_layer",
                        "global_spatial_pooling": True,
                        "normalization": "l2",
                        "dimension": int(vector.size),
                        "crop": list(crop) if crop is not None else None,
                        "source_image_sha256": sha256(path.read_bytes()).hexdigest(),
                        "semantic_embedding": True,
                    },
                )
            )
        return results

    def unload(self) -> None:
        self._model = None
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            return


def color_texture_embedding(image: Image.Image) -> tuple[list[float], dict[str, Any]]:
    """Generate a deterministic, dependency-light color/texture embedding.

    This provider is suitable for diversity sampling and automated tests. It is not
    presented as a semantic foundation-model embedding.
    """

    rgb = image.convert("RGB").resize((64, 64))
    values = np.asarray(rgb, dtype=np.float32) / 255.0
    features: list[float] = []
    for channel in range(3):
        histogram, _ = np.histogram(values[..., channel], bins=16, range=(0, 1), density=True)
        features.extend(histogram.astype(np.float32).tolist())
        features.extend(
            [
                float(np.mean(values[..., channel])),
                float(np.std(values[..., channel])),
                float(np.percentile(values[..., channel], 10)),
                float(np.percentile(values[..., channel], 50)),
                float(np.percentile(values[..., channel], 90)),
            ]
        )
    gray = np.asarray(rgb.convert("L"), dtype=np.float32) / 255.0
    gradient_x = np.diff(gray, axis=1, prepend=gray[:, :1])
    gradient_y = np.diff(gray, axis=0, prepend=gray[:1, :])
    magnitude = np.sqrt(gradient_x**2 + gradient_y**2)
    orientation = np.arctan2(gradient_y, gradient_x)
    magnitude_histogram, _ = np.histogram(magnitude, bins=16, range=(0, 1), density=True)
    orientation_histogram, _ = np.histogram(
        orientation,
        bins=16,
        range=(-np.pi, np.pi),
        weights=magnitude,
        density=False,
    )
    orientation_total = float(orientation_histogram.sum())
    if orientation_total > 0:
        orientation_histogram = orientation_histogram / orientation_total
    features.extend(np.nan_to_num(magnitude_histogram).astype(np.float32).tolist())
    features.extend(np.nan_to_num(orientation_histogram).astype(np.float32).tolist())
    # Preserve coarse spatial structure through an 8x8 grayscale grid.
    coarse = np.asarray(rgb.convert("L").resize((8, 8)), dtype=np.float32) / 255.0
    features.extend(coarse.reshape(-1).tolist())
    vector = np.asarray(features, dtype=np.float32)
    norm = float(np.linalg.norm(vector))
    if norm <= 0:
        vector[0] = 1.0
        norm = 1.0
    vector /= norm
    return vector.tolist(), {
        "runtime": "reefvision.color_texture_v1",
        "dimension": int(vector.size),
        "semantic_embedding": False,
        "input_size": [64, 64],
    }


def transformers_embedding(
    image: Image.Image,
    *,
    model_id: str,
    device: str,
    local_files_only: bool,
) -> tuple[list[float], dict[str, Any]]:
    """Generate a pooled embedding from a local Transformers vision model."""

    try:
        import torch
        from transformers import AutoImageProcessor, AutoModel
    except ImportError as exc:
        raise ValidationError(
            "Transformer embeddings require the optional torch and transformers dependencies"
        ) from exc
    normalized_device = device.strip().casefold()
    if normalized_device in {"", "auto"}:
        normalized_device = "cuda" if torch.cuda.is_available() else "cpu"
    try:
        processor = AutoImageProcessor.from_pretrained(  # type: ignore[no-untyped-call]
            model_id,
            local_files_only=local_files_only,
        )
        model = AutoModel.from_pretrained(
            model_id,
            local_files_only=local_files_only,
        )
    except Exception as exc:
        note = (
            " Install or import the model locally before embedding generation."
            if local_files_only
            else " Check the model ID and network access."
        )
        raise ValidationError(f"Embedding model could not be loaded.{note}") from exc
    model.to(normalized_device)
    model.eval()
    inputs = processor(images=image.convert("RGB"), return_tensors="pt")
    inputs = {key: value.to(normalized_device) for key, value in inputs.items()}
    with torch.inference_mode():
        outputs = model(**inputs)
    pooled = getattr(outputs, "pooler_output", None)
    if pooled is None:
        hidden = getattr(outputs, "last_hidden_state", None)
        if hidden is None:
            raise ValidationError("The selected vision model exposes no poolable hidden state")
        pooled = hidden.mean(dim=1)
    vector = pooled[0].detach().float().cpu().numpy().astype(np.float32)
    norm = float(np.linalg.norm(vector))
    if norm <= 0:
        raise ValidationError("The selected embedding model produced an all-zero vector")
    vector /= norm
    return vector.tolist(), {
        "runtime": "transformers.AutoModel",
        "model_id": model_id,
        "resolved_device": normalized_device,
        "local_files_only": local_files_only,
        "dimension": int(vector.size),
        "semantic_embedding": True,
    }


def generate_image_embedding(
    image_path: Path,
    *,
    provider_id: str,
    model_id: str,
    device: str,
    local_files_only: bool,
) -> tuple[list[float], dict[str, Any]]:
    if not image_path.is_file():
        raise ValidationError("The managed source image is missing")
    try:
        with Image.open(image_path) as source:
            source.load()
            image = source.convert("RGB")
    except OSError as exc:
        raise ValidationError("The managed source image could not be read") from exc
    if provider_id == "color_texture_v1":
        vector, metadata = color_texture_embedding(image)
    elif provider_id == "transformers_vision":
        vector, metadata = transformers_embedding(
            image,
            model_id=model_id,
            device=device,
            local_files_only=local_files_only,
        )
    else:
        raise ValidationError("Unsupported image-embedding provider")
    metadata.update(
        {
            "provider_id": provider_id,
            "model_id": model_id,
            "source_image_sha256": sha256(image_path.read_bytes()).hexdigest(),
        }
    )
    return vector, metadata
