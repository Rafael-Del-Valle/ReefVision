"""Revision-safe raster mask brush editing helpers."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import cast
from uuid import uuid4

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps, UnidentifiedImageError

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
            if source.mode in {"I;16", "I;16L", "I;16B"}:
                normalized = source.point(lambda value: value / 257).convert("L")
                return cast(Image.Image, normalized.convert("RGB"))
            return cast(Image.Image, source.convert("RGB"))
    except (OSError, UnidentifiedImageError) as exc:
        raise ValidationError("The managed source image could not be read") from exc


def polygon_from_binary_region(mask: Image.Image) -> list[tuple[int, int]]:
    """Trace exact pixel edges; simplify only collinear vertices, never fill holes."""
    bounds = mask.getbbox()
    if bounds is None:
        raise ValidationError("Fill produced an empty region")
    width, height = mask.size
    pixels = mask.load()
    if pixels is None:
        raise ValidationError("Fill pixels could not be accessed")
    edges: dict[tuple[int, int], tuple[int, int]] = {}

    def occupied(x: int, y: int) -> bool:
        return 0 <= x < width and 0 <= y < height and bool(pixels[x, y])

    def add(start: tuple[int, int], end: tuple[int, int]) -> None:
        if start in edges:
            raise ValidationError("Fill has touching boundaries; use Polygon or Brush instead")
        edges[start] = end

    left, top, right, bottom = bounds
    for y in range(top, bottom):
        for x in range(left, right):
            if not occupied(x, y):
                continue
            if not occupied(x, y - 1):
                add((x, y), (x + 1, y))
            if not occupied(x + 1, y):
                add((x + 1, y), (x + 1, y + 1))
            if not occupied(x, y + 1):
                add((x + 1, y + 1), (x, y + 1))
            if not occupied(x - 1, y):
                add((x, y + 1), (x, y))
    start = min(edges, key=lambda point: (point[1], point[0]))
    outline = [start]
    point = edges.pop(start)
    while point != start:
        outline.append(point)
        following = edges.pop(point, None)
        if following is None:
            raise ValidationError("Fill boundary cannot be represented as a simple polygon")
        point = following
    if edges:
        raise ValidationError(
            "Fill contains holes or separate regions; use Polygon or Brush instead"
        )
    simplified = []
    for index, point in enumerate(outline):
        previous = outline[index - 1]
        following = outline[(index + 1) % len(outline)]
        if (point[0] - previous[0]) * (following[1] - point[1]) != (point[1] - previous[1]) * (
            following[0] - point[0]
        ):
            simplified.append(point)
    # Existing polygon validation checks segment intersections pairwise. Bound
    # editor/save work instead of silently discarding fine image structure.
    if len(simplified) > 4096:
        raise ValidationError("Fill boundary is too complex; adjust tolerance or use Brush")
    return simplified


def polygon_fill_from_source(
    source: Image.Image, *, seed_x: int, seed_y: int, tolerance: int
) -> list[tuple[int, int]]:
    if not (0 <= seed_x < source.width and 0 <= seed_y < source.height):
        raise ValidationError("Fill seed must be inside the image")
    if not 0 <= tolerance <= 255:
        raise ValidationError("Fill tolerance must be between 0 and 255")
    mask = Image.new("L", source.size, 0)
    _flood_fill_from_source(mask, source, seed_x=seed_x, seed_y=seed_y, tolerance=tolerance)
    return polygon_from_binary_region(mask)


def polygon_fill_from_managed_image(
    settings: Settings,
    *,
    source_path: str,
    expected_size: tuple[int, int],
    seed_x: int,
    seed_y: int,
    tolerance: int,
) -> list[tuple[int, int]]:
    source = _load_source_image(
        settings, source_image_relative_path=source_path, expected_size=expected_size
    )
    return polygon_fill_from_source(source, seed_x=seed_x, seed_y=seed_y, tolerance=tolerance)


def _connected_binary_component(
    mask: Image.Image,
    *,
    seed_x: int,
    seed_y: int,
) -> Image.Image:
    if not (0 <= seed_x < mask.width and 0 <= seed_y < mask.height):
        raise ValidationError("Smart Close seed must be inside the image")
    working = mask.convert("L").point(lambda value: 255 if value > 0 else 0)
    if working.getpixel((seed_x, seed_y)) == 0:
        raise ValidationError(
            "Smart Close removed the clicked opening; reduce Auto-close tolerance"
        )
    ImageDraw.floodfill(working, (seed_x, seed_y), 128, thresh=0)
    return working.point(lambda value: 255 if value == 128 else 0)


def _fill_binary_holes(mask: Image.Image) -> Image.Image:
    binary = mask.convert("L").point(lambda value: 255 if value > 0 else 0)
    inverted = ImageOps.invert(binary)
    padded = Image.new("L", (binary.width + 2, binary.height + 2), 255)
    padded.paste(inverted, (1, 1))
    ImageDraw.floodfill(padded, (0, 0), 128, thresh=0)
    interior = padded.crop((1, 1, binary.width + 1, binary.height + 1))
    holes = interior.point(lambda value: 255 if value == 255 else 0)
    return ImageChops.lighter(binary, holes)


def smart_close_polygon_from_source(
    source: Image.Image,
    *,
    seed_x: int,
    seed_y: int,
    closure_strength: int,
) -> list[tuple[int, int]]:
    if not (0 <= seed_x < source.width and 0 <= seed_y < source.height):
        raise ValidationError("Smart Close seed must be inside the image")
    if not 0 <= closure_strength <= 100:
        raise ValidationError("Auto-close tolerance must be between 0 and 100")

    grayscale = source.convert("L")
    seed_value = int(grayscale.getpixel((seed_x, seed_y)))

    # Strength 0 intentionally favors the full visible opening. As strength
    # increases, the accepted intensity band tightens and a larger morphology
    # kernel removes narrow leaks through weak or broken boundary pixels.
    intensity_tolerance = max(10, round(56 - (closure_strength * 0.42)))
    candidate = grayscale.point(
        lambda value: 255 if abs(int(value) - seed_value) <= intensity_tolerance else 0
    )

    max_radius = max(
        1,
        min(32, round(min(source.width, source.height) * 0.015)),
    )
    radius = round(max_radius * (closure_strength / 100))
    if radius > 0:
        kernel = radius * 2 + 1
        # Opening the candidate region severs narrow connections from the
        # clicked opening into similarly toned exterior pixels.
        candidate = candidate.filter(ImageFilter.MinFilter(kernel))
        candidate = candidate.filter(ImageFilter.MaxFilter(kernel))

    component = _connected_binary_component(
        candidate,
        seed_x=seed_x,
        seed_y=seed_y,
    )
    component = _fill_binary_holes(component)
    return polygon_from_binary_region(component)


def smart_close_polygon_from_managed_image(
    settings: Settings,
    *,
    source_path: str,
    expected_size: tuple[int, int],
    seed_x: int,
    seed_y: int,
    closure_strength: int,
) -> list[tuple[int, int]]:
    source = _load_source_image(
        settings,
        source_image_relative_path=source_path,
        expected_size=expected_size,
    )
    return smart_close_polygon_from_source(
        source,
        seed_x=seed_x,
        seed_y=seed_y,
        closure_strength=closure_strength,
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
    source_image_relative_path: str | None = None,
    strokes: list[RasterEditStroke],
    brush_radius: float,
    mode: str,
    fill_tolerance: int = 24,
) -> tuple[
    str | None,
    Path | None,
    int,
    tuple[float, float, float, float] | None,
]:
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
        if mode == "erase":
            return None, None, 0, None
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
