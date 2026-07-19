"""Lightroom-style seed-guided raster Auto Mask helpers."""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import cast

from PIL import Image, ImageChops, ImageFilter, UnidentifiedImageError

from reefvision.config import Settings
from reefvision.domain.errors import ValidationError
from reefvision.schemas.raster_edits import RasterEditStroke
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.storage.raster_edits import (
    _draw_stroke,
    _load_source_mask,
    _neighbor_indices,
    _write_binary_revision,
)


def _load_rgb_source(
    settings: Settings,
    managed_path: str,
    expected_size: tuple[int, int],
) -> Image.Image:
    source = resolve_managed_project_path(settings, managed_path)
    if not source.is_file():
        raise ValidationError("The source image required for Auto Mask is missing")
    try:
        with Image.open(source) as image:
            image.load()
            if image.size != expected_size:
                raise ValidationError("Auto Mask source dimensions do not match the image")
            return cast(Image.Image, image.convert("RGB"))
    except (OSError, UnidentifiedImageError) as exc:
        raise ValidationError(
            "The source image required for Auto Mask could not be read"
        ) from exc


def _luminance(rgb: tuple[int, int, int]) -> float:
    red, green, blue = rgb
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _seed_colors(
    image: Image.Image,
    stroke: RasterEditStroke,
    *,
    sample_radius: int,
    limit: int = 96,
) -> list[tuple[int, int, int]]:
    width, height = image.size
    pixels = image.load()
    colors: list[tuple[int, int, int]] = []
    sample_area = max((sample_radius * 2 + 1) ** 2, 1)
    points_per_limit = max(limit // sample_area, 1)
    stride = max(1, len(stroke.points) // points_per_limit)
    for point in stroke.points[::stride]:
        center_x = min(width - 1, max(0, round(float(point.x))))
        center_y = min(height - 1, max(0, round(float(point.y))))
        for offset_y in range(-sample_radius, sample_radius + 1):
            for offset_x in range(-sample_radius, sample_radius + 1):
                x = center_x + offset_x
                y = center_y + offset_y
                if 0 <= x < width and 0 <= y < height:
                    color = pixels[x, y]
                    colors.append((int(color[0]), int(color[1]), int(color[2])))
                    if len(colors) >= limit:
                        return colors
    return colors


def _pixel_allowed(
    color: tuple[int, int, int],
    *,
    seeds: list[tuple[int, int, int]],
    color_tolerance_squared: float,
    luminance_tolerance: float,
    edge_value: int,
    edge_limit: float,
) -> bool:
    if edge_value > edge_limit:
        return False
    pixel_luminance = _luminance(color)
    for seed in seeds:
        if abs(pixel_luminance - _luminance(seed)) > luminance_tolerance:
            continue
        distance_squared = sum(
            (float(left) - float(right)) ** 2
            for left, right in zip(color, seed, strict=True)
        )
        if distance_squared <= color_tolerance_squared:
            return True
    return False


def _accepted_footprint(
    source: Image.Image,
    stroke: RasterEditStroke,
    *,
    brush_radius: float,
    color_tolerance: float,
    luminance_tolerance: float,
    edge_sensitivity: float,
    contiguous: bool,
    sample_radius: int,
) -> Image.Image:
    width, height = source.size
    footprint = Image.new("L", source.size, 0)
    _draw_stroke(footprint, stroke, radius=brush_radius, fill=255)
    bounds = footprint.getbbox()
    if bounds is None:
        return footprint

    seeds = _seed_colors(source, stroke, sample_radius=sample_radius)
    if not seeds:
        return Image.new("L", source.size, 0)
    source_pixels = source.load()
    footprint_bytes = bytearray(footprint.tobytes())
    edge_bytes = source.convert("L").filter(ImageFilter.FIND_EDGES).tobytes()
    allowed = bytearray(width * height)
    left, top, right, bottom = bounds
    color_tolerance_squared = float(color_tolerance) ** 2
    # Sensitivity 0 allows nearly every edge. Sensitivity 1 stops at modest gradients.
    edge_limit = 255.0 - float(edge_sensitivity) * 220.0
    for y in range(top, bottom):
        row_offset = y * width
        for x in range(left, right):
            index = row_offset + x
            if footprint_bytes[index] == 0:
                continue
            raw_color = source_pixels[x, y]
            color = (int(raw_color[0]), int(raw_color[1]), int(raw_color[2]))
            if _pixel_allowed(
                color,
                seeds=seeds,
                color_tolerance_squared=color_tolerance_squared,
                luminance_tolerance=float(luminance_tolerance),
                edge_value=edge_bytes[index],
                edge_limit=edge_limit,
            ):
                allowed[index] = 255

    if not contiguous:
        return Image.frombytes("L", source.size, bytes(allowed))

    accepted = bytearray(width * height)
    queue: deque[int] = deque()
    for point in stroke.points:
        seed_x = min(width - 1, max(0, round(float(point.x))))
        seed_y = min(height - 1, max(0, round(float(point.y))))
        seed_index = seed_y * width + seed_x
        if allowed[seed_index] and not accepted[seed_index]:
            accepted[seed_index] = 255
            queue.append(seed_index)
    # A seed can fall directly on an edge. Find a nearby allowed point inside the brush.
    if not queue:
        for index, value in enumerate(allowed):
            if value:
                accepted[index] = 255
                queue.append(index)
                break
    while queue:
        current = queue.popleft()
        for neighbor in _neighbor_indices(
            current,
            width=width,
            height=height,
            connectivity=8,
        ):
            if allowed[neighbor] and not accepted[neighbor]:
                accepted[neighbor] = 255
                queue.append(neighbor)
    return Image.frombytes("L", source.size, bytes(accepted))


def write_raster_automask_revision(
    settings: Settings,
    *,
    project_storage_root: str,
    source_image_relative_path: str,
    image_id: str,
    mask_annotation_id: str,
    revision: int,
    source_mask_relative_path: str | None,
    expected_width: int,
    expected_height: int,
    strokes: list[RasterEditStroke],
    brush_radius: float,
    mode: str,
    color_tolerance: float,
    luminance_tolerance: float,
    edge_sensitivity: float,
    contiguous: bool,
    sample_radius: int,
) -> tuple[str, Path, int, tuple[float, float, float, float]]:
    """Apply color/luminance/edge-aware strokes and publish an immutable revision."""

    expected_size = (expected_width, expected_height)
    source = _load_rgb_source(settings, source_image_relative_path, expected_size)
    mask = _load_source_mask(
        settings,
        source_relative_path=source_mask_relative_path,
        expected_size=expected_size,
    ).point(lambda value: 255 if value > 0 else 0)
    accepted = Image.new("L", expected_size, 0)
    for stroke in strokes:
        selected = _accepted_footprint(
            source,
            stroke,
            brush_radius=brush_radius,
            color_tolerance=color_tolerance,
            luminance_tolerance=luminance_tolerance,
            edge_sensitivity=edge_sensitivity,
            contiguous=contiguous,
            sample_radius=sample_radius,
        )
        accepted = ImageChops.lighter(accepted, selected)
    if accepted.getbbox() is None:
        raise ValidationError(
            "Auto Mask did not find pixels similar enough to the selected stroke seeds"
        )
    if mode == "paint":
        binary = ImageChops.lighter(mask, accepted)
    else:
        inverse = ImageChops.invert(accepted)
        binary = ImageChops.multiply(mask, inverse)
    binary = binary.point(lambda value: 255 if value > 0 else 0)
    return _write_binary_revision(
        settings,
        project_storage_root=project_storage_root,
        image_id=image_id,
        mask_annotation_id=mask_annotation_id,
        revision=revision,
        binary=binary,
    )
