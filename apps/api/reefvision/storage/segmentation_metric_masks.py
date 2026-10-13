"""Exact source-image raster/polygon conversion for scientific mask scoring.

The returned row runs are sorted, non-overlapping and half-open. Raster holes
and disconnected components survive conversion; bounding boxes are never used.
"""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw, UnidentifiedImageError

from reefvision.domain.segmentation_evaluation import ScoredInstanceMask
from reefvision.domain.segmentation_holdout import _validate_polygon

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_MASK_PIXELS = 100_000_000
MAX_MASK_PNG_BYTES = 256 * 1024 * 1024


def _dimensions(width: int, height: int) -> None:
    if (
        type(width) is not int
        or type(height) is not int
        or width < 1
        or height < 1
        or width * height > MAX_MASK_PIXELS
    ):
        raise ValueError("Invalid or oversized source-image mask dimensions")


def binary_mask_to_runs(
    mask: Image.Image, *, width: int, height: int
) -> tuple[tuple[int, int, int], ...]:
    """Retain each nonzero pixel as part of a half-open source-pixel run."""
    _dimensions(width, height)
    if mask.size != (width, height):
        raise ValueError("Mask pixel dimensions differ from source image")
    try:
        pixels = mask.convert("L").tobytes()
    except (OSError, ValueError) as exc:
        raise ValueError("Cannot decode raster mask pixels") from exc
    spans: list[tuple[int, int, int]] = []
    for y in range(height):
        base = y * width
        start: int | None = None
        for x in range(width):
            filled = pixels[base + x] != 0
            if filled and start is None:
                start = x
            elif not filled and start is not None:
                spans.append((y, start, x))
                start = None
        if start is not None:
            spans.append((y, start, width))
    if not spans:
        raise ValueError("Evaluation mask contains no occupied source pixels")
    return tuple(spans)


def png_to_runs(
    payload: bytes, *, width: int, height: int
) -> tuple[tuple[int, int, int], ...]:
    """Decode a complete source-sized PNG, rejecting corruption and size drift."""
    _dimensions(width, height)
    if not payload.startswith(PNG_SIGNATURE) or len(payload) > MAX_MASK_PNG_BYTES:
        raise ValueError("Evaluation mask is not a supported source PNG")
    try:
        with Image.open(BytesIO(payload)) as image:
            if image.format != "PNG" or image.size != (width, height):
                raise ValueError("Raster mask PNG source dimensions are inconsistent")
            image.load()
            return binary_mask_to_runs(image, width=width, height=height)
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ValueError("Evaluation mask PNG is unreadable or unsafe") from exc


def polygon_to_runs(
    vertices: list[list[float]], *, width: int, height: int
) -> tuple[tuple[int, int, int], ...]:
    """Rasterize a simple polygon using the documented Pillow fill convention.

    Coordinates use source-image pixels; the output's row intervals are
    half-open. Polygons and raster masks are not treated as bounding boxes.
    """
    _dimensions(width, height)
    _validate_polygon(vertices, width=width, height=height)
    points = [(float(x), float(y)) for x, y in vertices]
    if len(points) > 3 and points[0] == points[-1]:
        points.pop()
    raster = Image.new("L", (width, height), 0)
    ImageDraw.Draw(raster).polygon(points, fill=255)
    return binary_mask_to_runs(raster, width=width, height=height)


def make_scored_mask(
    runs: tuple[tuple[int, int, int], ...],
    *,
    image_id: str,
    class_id: str,
    score: float,
    width: int,
    height: int,
) -> ScoredInstanceMask:
    """Bind exact mask pixels to image/class identity and confidence."""
    return ScoredInstanceMask(image_id, class_id, score, width, height, runs)
