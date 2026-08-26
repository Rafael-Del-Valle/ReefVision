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


def _source_color_within_tolerance(
    pixel: tuple[int, int, int],
    target: tuple[int, int, int],
    tolerance: int,
) -> bool:
    return max(abs(int(pixel[index]) - int(target[index])) for index in range(3)) <= tolerance


def _flood_fill_from_source(
    mask: Image.Image,
    source: Image.Image,
    *,
    seed_x: int,
    seed_y: int,
    tolerance: int,
) -> int:
    """Fill the contiguous source-image color region into the annotation mask."""
    source_rgb = source.convert("RGB")
    if source_rgb.size != mask.size:
        raise ValidationError("Source image dimensions do not match the raster mask")

    width, height = mask.size
    if width <= 0 or height <= 0:
        raise ValidationError("Cannot flood-fill an empty image")

    seed_x = max(0, min(width - 1, int(seed_x)))
    seed_y = max(0, min(height - 1, int(seed_y)))
    source_pixels = source_rgb.load()
    mask_pixels = mask.load()
    if source_pixels is None or mask_pixels is None:
        raise ValidationError("Image pixels could not be accessed for flood fill")

    target = cast(tuple[int, int, int], source_pixels[seed_x, seed_y])
    visited = bytearray(width * height)
    pending: list[tuple[int, int]] = [(seed_x, seed_y)]
    filled = 0

    def matches(x: int, y: int) -> bool:
        if x < 0 or y < 0 or x >= width or y >= height:
            return False
        if visited[y * width + x]:
            return False
        pixel = cast(tuple[int, int, int], source_pixels[x, y])
        return _source_color_within_tolerance(pixel, target, tolerance)

    while pending:
        start_x, y = pending.pop()
        if not matches(start_x, y):
            continue
        left = start_x
        while left > 0 and matches(left - 1, y):
            left -= 1

        span_up = False
        span_down = False
        x = left
        while x < width and matches(x, y):
            visited[y * width + x] = 1
            mask_pixels[x, y] = 255
            filled += 1

            if y > 0:
                up_matches = matches(x, y - 1)
                if up_matches and not span_up:
                    pending.append((x, y - 1))
                    span_up = True
                elif not up_matches:
                    span_up = False

            if y + 1 < height:
                down_matches = matches(x, y + 1)
                if down_matches and not span_down:
                    pending.append((x, y + 1))
                    span_down = True
                elif not down_matches:
                    span_down = False
            x += 1

    return filled


def _load_source_image(
    settings: Settings,
    *,
    source_image_relative_path: str,
    expected_size: tuple[int, int],
) -> Image.Image:
    source_path = resolve_managed_project_path(settings, source_image_relative_path)
    if not source_path.is_file():
        raise ValidationError("The managed source image is missing")
    try:
        with Image.open(source_path) as source:
            source.load()
            if source.size != expected_size:
                raise ValidationError("Source image dimensions do not match the raster mask")
            return cast(Image.Image, source.convert("RGB"))
    except (OSError, UnidentifiedImageError) as exc:
        raise ValidationError("The managed source image could not be read") from exc


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
    source_image_relative_path: str | None = None,
    strokes: list[RasterEditStroke],
    brush_radius: float,
    mode: str,
    fill_tolerance: int = 24,
) -> tuple[str, Path, int, tuple[float, float, float, float]]:
    """Apply brush edits and atomically write a new immutable mask revision."""

    mask = _load_source_mask(
        settings,
        source_relative_path=source_relative_path,
        expected_size=(expected_width, expected_height),
    )
    if mode == "fill":
        if source_image_relative_path is None:
            raise ValidationError("Flood fill requires the managed source image")
        if not strokes or not strokes[0].points:
            raise ValidationError("Flood fill requires a seed point")
        source = _load_source_image(
            settings,
            source_image_relative_path=source_image_relative_path,
            expected_size=(expected_width, expected_height),
        )
        seed = strokes[0].points[0]
        _flood_fill_from_source(
            mask,
            source,
            seed_x=round(float(seed.x)),
            seed_y=round(float(seed.y)),
            tolerance=fill_tolerance,
        )
    elif mode in {"paint", "erase"}:
        fill = 255 if mode == "paint" else 0
        for stroke in strokes:
            _draw_stroke(mask, stroke, radius=brush_radius, fill=fill)
    else:
        raise ValidationError(f"Unsupported raster edit mode: {mode}")

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
    # Keep the temporary basename short enough to stay below the legacy Windows
    # MAX_PATH limit even inside deeply nested pytest temporary directories.
    temporary = destination_directory / f".rv-{uuid4().hex[:8]}.tmp"
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
