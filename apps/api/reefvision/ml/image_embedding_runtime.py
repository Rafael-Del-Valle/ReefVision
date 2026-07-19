"""Automatic image-embedding providers for active learning."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from reefvision.domain.errors import ValidationError


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
        density=True,
    )
    features.extend(np.nan_to_num(magnitude_histogram).astype(np.float32).tolist())
    features.extend(np.nan_to_num(orientation_histogram).astype(np.float32).tolist())
    # Preserve coarse spatial structure through an 8×8 grayscale grid.
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
        processor = AutoImageProcessor.from_pretrained(
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
