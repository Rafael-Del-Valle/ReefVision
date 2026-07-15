"""Revision-safe raster mask brush editing helpers."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import cast
from uuid import uuid4

from PIL import Image, ImageDraw, UnidentifiedImageError

from reefvision.config import Settings
from reefvision.domain.errors import ConflictError, ValidationError
from reefvision.schemas.raster_edits import RasterEditStroke
from reefvision.storage.projects import resolve_managed_project_path


def _load_source_mask(
    settings: Settings,
    *,
    source_relative_path: str | None,
    expected_size: tuple[int, int],
) -> Image.Image:
    if source_relative_path is None:
        return Image.new("L", expected_size, 0)
    source = resolve_managed_project_path(settings, source_relative_path)
    if not source.is_file():
        raise ValidationError("The raster mask content file is missing")
    try:
        with Image.open(source) as image:
            image.load()
            if image.size != expected_size:
                raise ValidationError("Raster mask dimensions do not match the source image")
            return cast(Image.Image, image.convert("L"))
    except (OSError, UnidentifiedImageError) as exc:
        raise ValidationError("Raster mask content could not be read") from exc


def _draw_stroke(
    image: Image.Image,
    stroke: RasterEditStroke,
    *,
    radius: float,
    fill: int,
) -> None:
    draw = ImageDraw.Draw(image)
    points = [(float(point.x), float(point.y)) for point in stroke.points]
    width = max(1, round(radius * 2.0))
    if len(points) > 1:
        draw.line(points, fill=fill, width=width, joint="curve")
    for x, y in points:
        draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius),
            fill=fill,
        )


def _publish_revision_exclusively(temporary: Path, destination: Path) -> None:
    """Publish a complete revision without replacing an existing immutable file."""

    try:
        os.link(temporary, destination)
    except FileExistsError as exc:
        raise ConflictError("Raster mask revision already exists") from exc
    except OSError:
        # Hard links can be unavailable on unusual filesystems. The exclusive
        # fallback still guarantees that a committed revision is never replaced.
        try:
            with temporary.open("rb") as source, destination.open("xb") as target:
                shutil.copyfileobj(source, target)
                target.flush()
                os.fsync(target.fileno())
        except FileExistsError as exc:
            raise ConflictError("Raster mask revision already exists") from exc
        except Exception:
            destination.unlink(missing_ok=True)
            raise
    finally:
        temporary.unlink(missing_ok=True)


def write_raster_mask_revision(
    settings: Settings,
    *,
    project_storage_root: str,
    image_id: str,
    mask_annotation_id: str,
    revision: int,
    source_relative_path: str | None,
    expected_width: int,
    expected_height: int,
    strokes: list[RasterEditStroke],
    brush_radius: float,
    mode: str,
) -> tuple[str, Path, int, tuple[float, float, float, float]]:
    """Apply brush edits and atomically write a new immutable mask revision."""

    mask = _load_source_mask(
        settings,
        source_relative_path=source_relative_path,
        expected_size=(expected_width, expected_height),
    )
    fill = 255 if mode == "paint" else 0
    for stroke in strokes:
        _draw_stroke(mask, stroke, radius=brush_radius, fill=fill)

    binary = mask.point(lambda value: 255 if value > 0 else 0)
    bounds = binary.getbbox()
    if bounds is None:
        raise ValidationError("Raster mask edits cannot produce an empty mask")
    histogram = binary.histogram()
    area_pixels = int(sum(histogram[1:]))

    project_root = resolve_managed_project_path(settings, project_storage_root)
    destination_directory = project_root / "masks" / image_id
    destination_directory.mkdir(parents=True, exist_ok=True)
    destination = destination_directory / f"{mask_annotation_id}-r{revision}.png"
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        binary.save(temporary, format="PNG", optimize=True)
        _publish_revision_exclusively(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    relative_path = destination.relative_to(settings.resolved_data_dir).as_posix()
    left, top, right, bottom = bounds
    return (
        relative_path,
        destination,
        area_pixels,
        (float(left), float(top), float(right), float(bottom)),
    )
