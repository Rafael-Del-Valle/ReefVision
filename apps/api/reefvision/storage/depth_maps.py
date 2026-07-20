"""Immutable aligned depth-map storage and visualization helpers."""

from __future__ import annotations

import os
import shutil
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from reefvision.config import Settings
from reefvision.domain.errors import ConflictError, ValidationError
from reefvision.storage.projects import resolve_managed_project_path


def _publish_exclusively(temporary: Path, destination: Path) -> None:
    """Publish without replacing an artifact created by another worker."""

    try:
        os.link(temporary, destination)
    except FileExistsError as exc:
        raise ConflictError("Depth map artifact already exists") from exc
    except OSError:
        try:
            with temporary.open("rb") as source, destination.open("xb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
                target.flush()
                os.fsync(target.fileno())
        except FileExistsError as exc:
            raise ConflictError("Depth map artifact already exists") from exc
    temporary.unlink(missing_ok=True)


def validate_depth_array(
    values: NDArray[Any],
    *,
    expected_width: int,
    expected_height: int,
    depth_kind: str,
) -> NDArray[Any]:
    array = np.asarray(values, dtype=np.float32)
    if array.ndim != 2:
        raise ValidationError("Depth maps must be two-dimensional")
    if array.shape != (expected_height, expected_width):
        raise ValidationError("Depth map dimensions do not match the source image")
    finite = np.isfinite(array)
    if not finite.any():
        raise ValidationError("Depth maps must contain at least one finite value")
    if depth_kind == "metric" and np.any(array[finite] <= 0):
        raise ValidationError("Metric depth values must be greater than zero")
    result = array.copy()
    result[~finite] = np.nan
    return result


def _preview_image(values: NDArray[Any]) -> Image.Image:
    finite = np.isfinite(values)
    valid = values[finite]
    low = float(np.percentile(valid, 2))
    high = float(np.percentile(valid, 98))
    if high <= low:
        high = low + 1.0
    normalized = np.zeros(values.shape, dtype=np.float32)
    normalized[finite] = np.clip((values[finite] - low) / (high - low), 0, 1)
    # Invert so nearer values appear brighter for conventional depth viewing.
    preview = np.round((1.0 - normalized) * 255).astype(np.uint8)
    preview[~finite] = 0
    return Image.fromarray(preview, mode="L")


def write_depth_map(
    settings: Settings,
    *,
    project_storage_root: str,
    image_id: str,
    depth_map_id: str,
    values: NDArray[Any],
    expected_width: int,
    expected_height: int,
    depth_kind: str,
) -> tuple[str, str, str, dict[str, float | int]]:
    array = validate_depth_array(
        values,
        expected_width=expected_width,
        expected_height=expected_height,
        depth_kind=depth_kind,
    )
    project_root = resolve_managed_project_path(settings, project_storage_root)
    directory = project_root / "depth" / image_id
    directory.mkdir(parents=True, exist_ok=True)
    data_path = directory / f"{depth_map_id}.npy"
    preview_path = directory / f"{depth_map_id}-preview.png"
    temporary_data = directory / f".rv-depth-{uuid4().hex[:8]}.npy"
    temporary_preview = directory / f".rv-depth-{uuid4().hex[:8]}.png"
    if data_path.exists() or preview_path.exists():
        raise ConflictError("Depth map artifact already exists")
    try:
        np.save(temporary_data, array, allow_pickle=False)
        _preview_image(array).save(temporary_preview, format="PNG", optimize=True)
        _publish_exclusively(temporary_data, data_path)
        _publish_exclusively(temporary_preview, preview_path)
    except Exception:
        temporary_data.unlink(missing_ok=True)
        temporary_preview.unlink(missing_ok=True)
        data_path.unlink(missing_ok=True)
        preview_path.unlink(missing_ok=True)
        raise

    digest = sha256(data_path.read_bytes()).hexdigest()
    finite = array[np.isfinite(array)]
    stats: dict[str, float | int] = {
        "minimum_depth": float(np.min(finite)),
        "maximum_depth": float(np.max(finite)),
        "median_depth": float(np.median(finite)),
        "valid_pixel_count": int(finite.size),
    }
    return (
        data_path.relative_to(settings.resolved_data_dir).as_posix(),
        preview_path.relative_to(settings.resolved_data_dir).as_posix(),
        digest,
        stats,
    )


def load_depth_map(
    settings: Settings,
    managed_path: str,
    *,
    expected_width: int | None = None,
    expected_height: int | None = None,
) -> NDArray[Any]:
    path = resolve_managed_project_path(settings, managed_path)
    if not path.is_file():
        raise ValidationError("Depth map content is missing")
    try:
        values = np.load(path, allow_pickle=False)
    except (OSError, ValueError) as exc:
        raise ValidationError("Depth map content could not be read") from exc
    if values.ndim != 2:
        raise ValidationError("Stored depth map is not two-dimensional")
    if (
        expected_width is not None
        and expected_height is not None
        and values.shape != (expected_height, expected_width)
    ):
        raise ValidationError("Stored depth map dimensions no longer match the image")
    return np.asarray(values, dtype=np.float32)
