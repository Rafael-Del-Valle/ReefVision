"""Safe managed storage operations for raster mask annotations."""

from __future__ import annotations

import base64
import binascii
import os
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from reefvision.config import Settings
from reefvision.domain.errors import ValidationError
from reefvision.storage.projects import resolve_managed_project_path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def write_mask_png(
    settings: Settings,
    *,
    project_storage_root: str,
    image_id: str,
    mask_annotation_id: str,
    png_base64: str,
    expected_width: int,
    expected_height: int,
) -> tuple[str, Path, int]:
    """Validate and atomically store a PNG beneath the managed project directory."""

    try:
        payload = base64.b64decode(png_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValidationError("Assist mask output is not valid base64 data") from exc
    if not payload.startswith(PNG_SIGNATURE):
        raise ValidationError("Assist mask output is not a PNG image")

    try:
        with Image.open(BytesIO(payload)) as image:
            image.load()
            if image.size != (expected_width, expected_height):
                raise ValidationError(
                    "Assist mask dimensions do not match the source image"
                )
            grayscale = image.convert("L")
            histogram = grayscale.histogram()
            area_pixels = int(sum(histogram[1:]))
    except (OSError, UnidentifiedImageError) as exc:
        raise ValidationError("Assist mask output is not a readable PNG image") from exc
    if area_pixels <= 0:
        raise ValidationError("Assist mask output is empty")

    project_root = resolve_managed_project_path(settings, project_storage_root)
    destination_directory = project_root / "masks" / image_id
    destination_directory.mkdir(parents=True, exist_ok=True)
    destination = destination_directory / f"{mask_annotation_id}.png"
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, destination)

    relative_path = destination.relative_to(settings.resolved_data_dir).as_posix()
    return relative_path, destination, area_pixels
