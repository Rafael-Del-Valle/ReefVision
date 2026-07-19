"""Revision-safe raster mask brush editing and cleanup helpers."""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
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


def _neighbor_indices(
    index: int,
    *,
    width: int,
    height: int,
    connectivity: int,
) -> Iterator[int]:
    x = index % width
    y = index // width
    offsets = (
        ((-1, 0), (1, 0), (0, -1), (0, 1))
        if connectivity == 4
        else (
            (-1, 0),
            (1, 0),
            (0, -1),
            (0, 1),
            (-1, -1),
            (1, -1),
            (-1, 1),
            (1, 1),
        )
    )
    for offset_x, offset_y in offsets:
        neighbor_x = x + offset_x
        neighbor_y = y + offset_y
        if 0 <= neighbor_x < width and 0 <= neighbor_y < height:
            yield neighbor_y * width + neighbor_x


def _foreground_components(
    pixels: bytearray,
    *,
    width: int,
    height: int,
    connectivity: int,
) -> list[list[int]]:
    visited = bytearray(len(pixels))
    components: list[list[int]] = []
    for start, value in enumerate(pixels):
        if value == 0 or visited[start]:
            continue
        visited[start] = 1
        stack = [start]
        component: list[int] = []
        while stack:
            current = stack.pop()
            component.append(current)
            for neighbor in _neighbor_indices(
                current,
                width=width,
                height=height,
                connectivity=connectivity,
            ):
                if pixels[neighbor] and not visited[neighbor]:
                    visited[neighbor] = 1
                    stack.append(neighbor)
        components.append(component)
    return components


def _fill_enclosed_background(
    pixels: bytearray,
    *,
    width: int,
    height: int,
    connectivity: int,
) -> None:
    exterior = bytearray(len(pixels))
    stack: list[int] = []
    border_indices = {
        *(x for x in range(width)),
        *((height - 1) * width + x for x in range(width)),
        *(y * width for y in range(height)),
        *(y * width + width - 1 for y in range(height)),
    }
    for index in border_indices:
        if pixels[index] == 0 and not exterior[index]:
            exterior[index] = 1
            stack.append(index)
    while stack:
        current = stack.pop()
        for neighbor in _neighbor_indices(
            current,
            width=width,
            height=height,
            connectivity=connectivity,
        ):
            if pixels[neighbor] == 0 and not exterior[neighbor]:
                exterior[neighbor] = 1
                stack.append(neighbor)
    for index, value in enumerate(pixels):
        if value == 0 and not exterior[index]:
            pixels[index] = 255


def _write_binary_revision(
    settings: Settings,
    *,
    project_storage_root: str,
    image_id: str,
    mask_annotation_id: str,
    revision: int,
    binary: Image.Image,
) -> tuple[str, Path, int, tuple[float, float, float, float]]:
    bounds = binary.getbbox()
    if bounds is None:
        raise ValidationError("Raster mask edits cannot produce an empty mask")
    histogram = binary.histogram()
    area_pixels = int(sum(histogram[1:]))

    project_root = resolve_managed_project_path(settings, project_storage_root)
    destination_directory = project_root / "masks" / image_id
    destination_directory.mkdir(parents=True, exist_ok=True)
    destination = destination_directory / f"{mask_annotation_id}-r{revision}.png"
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
    return _write_binary_revision(
        settings,
        project_storage_root=project_storage_root,
        image_id=image_id,
        mask_annotation_id=mask_annotation_id,
        revision=revision,
        binary=binary,
    )


def write_raster_mask_cleanup_revision(
    settings: Settings,
    *,
    project_storage_root: str,
    image_id: str,
    mask_annotation_id: str,
    revision: int,
    source_relative_path: str,
    expected_width: int,
    expected_height: int,
    remove_small_components: bool,
    minimum_component_area: int,
    keep_largest_component: bool,
    fill_holes: bool,
    connectivity: int,
) -> tuple[str, Path, int, tuple[float, float, float, float], dict[str, int]]:
    """Apply deterministic topology cleanup and write a new immutable revision."""

    source = _load_source_mask(
        settings,
        source_relative_path=source_relative_path,
        expected_size=(expected_width, expected_height),
    ).point(lambda value: 255 if value > 0 else 0)
    pixels = bytearray(source.tobytes())
    components = _foreground_components(
        pixels,
        width=expected_width,
        height=expected_height,
        connectivity=connectivity,
    )
    original_component_count = len(components)
    removed_component_count = 0

    if keep_largest_component and components:
        largest = max(components, key=len)
        largest_set = set(largest)
        for index, value in enumerate(pixels):
            if value and index not in largest_set:
                pixels[index] = 0
        removed_component_count += max(0, original_component_count - 1)
        components = [largest]

    if remove_small_components:
        for component in components:
            if len(component) < minimum_component_area:
                for index in component:
                    pixels[index] = 0
                removed_component_count += 1

    if fill_holes:
        _fill_enclosed_background(
            pixels,
            width=expected_width,
            height=expected_height,
            connectivity=connectivity,
        )

    binary = Image.frombytes("L", (expected_width, expected_height), bytes(pixels))
    relative, destination, area, bounds = _write_binary_revision(
        settings,
        project_storage_root=project_storage_root,
        image_id=image_id,
        mask_annotation_id=mask_annotation_id,
        revision=revision,
        binary=binary,
    )
    cleaned_components = _foreground_components(
        bytearray(binary.tobytes()),
        width=expected_width,
        height=expected_height,
        connectivity=connectivity,
    )
    return (
        relative,
        destination,
        area,
        bounds,
        {
            "original_component_count": original_component_count,
            "cleaned_component_count": len(cleaned_components),
            "removed_component_count": removed_component_count,
        },
    )
