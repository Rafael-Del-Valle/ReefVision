"""Managed image and proposal-mask I/O for automatic SAM generation."""

from __future__ import annotations

import base64
import io
from hashlib import sha256
from typing import Any

from PIL import Image, ImageDraw

from reefvision.config import Settings
from reefvision.domain.errors import ValidationError
from reefvision.storage.masks import write_mask_png
from reefvision.storage.projects import resolve_managed_project_path


def read_source(settings: Settings, managed_path: str) -> Image.Image:
    with Image.open(resolve_managed_project_path(settings, managed_path)) as source:
        source.load()
        converted: Image.Image = source.convert("RGB")
        return converted


def read_reference_mask(
    settings: Settings,
    mask_path: str | None,
    polygon: list[list[float]] | None,
    size: tuple[int, int],
) -> Any:
    import numpy as np

    if mask_path:
        with Image.open(resolve_managed_project_path(settings, mask_path)) as source:
            if source.size != size:
                raise ValidationError("Existing mask dimensions do not match source image")
            return np.asarray(source.convert("L")) > 0
    mask = Image.new("L", size)
    if polygon:
        ImageDraw.Draw(mask).polygon([(point[0], point[1]) for point in polygon], fill=255)
    return np.asarray(mask) > 0


def store_candidate(
    settings: Settings,
    *,
    storage_root: str,
    image_id: str,
    proposal_id: str,
    mask: Any,
    origin: tuple[int, int],
    size: tuple[int, int],
) -> tuple[str, str, tuple[float, float, float, float]]:
    output = Image.new("L", size)
    output.paste(Image.fromarray(mask.astype("uint8") * 255), origin)
    buffer = io.BytesIO()
    output.save(buffer, format="PNG")
    payload = buffer.getvalue()
    stored = write_mask_png(
        settings,
        project_storage_root=storage_root,
        image_id=image_id,
        mask_annotation_id=proposal_id,
        png_base64=base64.b64encode(payload).decode("ascii"),
        expected_width=size[0],
        expected_height=size[1],
    )
    return stored[0], sha256(payload).hexdigest(), (stored[3], stored[4], stored[5], stored[6])


def remove_candidates(settings: Settings, paths: list[str]) -> None:
    for path in paths:
        resolve_managed_project_path(settings, path).unlink(missing_ok=True)
