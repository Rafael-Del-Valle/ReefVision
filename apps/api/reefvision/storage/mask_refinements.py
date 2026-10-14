"""Canonical mask loading and immutable refinement candidate storage."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from reefvision.config import Settings
from reefvision.domain.errors import ValidationError
from reefvision.ml.providers import mask_to_png_base64
from reefvision.storage.masks import write_mask_png
from reefvision.storage.projects import resolve_managed_project_path

MAX_REFINEMENT_PIXELS = 16_000_000


def load_prior(settings: Settings, snapshot: dict[str, Any], width: int, height: int) -> Any:
    import numpy as np

    if width * height > MAX_REFINEMENT_PIXELS:
        raise ValidationError("Refinement supports images up to 16 million pixels; use a crop")
    if snapshot.get("geometry_kind") == "raster_mask":
        path = verified_file(settings, str(snapshot.get("mask_path") or ""))
        try:
            with Image.open(path) as image:
                if image.size != (width, height):
                    raise ValidationError("Mask dimensions do not match its source image")
                result = np.array(image.convert("L")) > 0
        except (OSError, UnidentifiedImageError) as exc:
            raise ValidationError("Cannot read persisted mask content") from exc
    elif snapshot.get("geometry_kind") == "polygon":
        polygon = snapshot.get("polygon_json")
        if not polygon or len(polygon) < 3:
            raise ValidationError("Persisted polygon geometry is invalid")
        points = np.asarray(polygon, dtype=float)
        if not np.isfinite(points).all() or points.ndim != 2 or points.shape[1] != 2:
            raise ValidationError("Persisted polygon geometry is invalid")
        if (points < 0).any() or (points[:, 0] > width).any() or (points[:, 1] > height).any():
            raise ValidationError("Persisted polygon extends outside its source image")
        # Pixel-center, even/odd scan conversion preserves source-pixel geometry.
        result = np.zeros((height, width), dtype=bool)
        xs = np.arange(width) + 0.5
        for y in range(max(0, int(points[:, 1].min())), min(height, int(points[:, 1].max()) + 1)):
            previous = points[-1]
            for current in points:
                if (current[1] > y + 0.5) != (previous[1] > y + 0.5):
                    cross = (previous[0] - current[0]) * (y + 0.5 - current[1]) / (
                        previous[1] - current[1]
                    ) + current[0]
                    result[y] ^= xs < cross
                previous = current
    else:
        raise ValidationError("Select a persisted editable polygon or raster mask")
    if not result.any():
        raise ValidationError("The selected mask has no foreground pixels")
    return result


def verified_file(settings: Settings, relative_path: str, checksum: str | None = None) -> Path:
    path = resolve_managed_project_path(settings, relative_path)
    if not path.is_file():
        raise ValidationError("Mask content is missing from managed storage")
    if checksum is not None and sha256(path.read_bytes()).hexdigest() != checksum:
        raise ValidationError("Mask content checksum does not match")
    return path


def save_candidate(
    settings: Settings, project_root: str, image_id: str, mask: Any
) -> dict[str, Any]:
    return save_candidate_png(
        settings, project_root, image_id, mask_to_png_base64(mask), mask.shape[1], mask.shape[0]
    )


def save_candidate_png(
    settings: Settings, project_root: str, image_id: str, png: str, width: int, height: int
) -> dict[str, Any]:
    path, absolute, area, x_min, y_min, x_max, y_max = write_mask_png(
        settings,
        project_storage_root=project_root,
        image_id=image_id,
        mask_annotation_id=str(uuid4()),
        png_base64=png,
        expected_width=width,
        expected_height=height,
    )
    return {
        "mask_path": path,
        "mask_sha256": sha256(absolute.read_bytes()).hexdigest(),
        "area_pixels": area,
        "x_min": x_min,
        "y_min": y_min,
        "x_max": x_max,
        "y_max": y_max,
    }
