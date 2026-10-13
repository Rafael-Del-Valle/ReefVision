"""Source-pixel raster and polygon conversion for scientific mask scoring.

Binary mask pixels become sorted, non-overlapping half-open row runs. Raster
holes and disconnected components are retained; no bounding-box substitutes.
"""

from __future__ import annotations

from io import BytesIO
from math import isfinite

from PIL import Image, ImageDraw, UnidentifiedImageError

from reefvision.domain.segmentation_evaluation import ScoredInstanceMask

PNG_SIGNATURE = b"\\x89PNG\\r\\n\\x1a\\n"
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
    """Retain every nonzero mask pixel as a source-pixel half-open row run."""
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
    """Convert source-sized PNG; corrupt data and dimension drift fail closed."""
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
    """Rasterize a prevalidated simple polygon using Pillow's inclusive fill.

    Source-pixel coordinates use Pillow's polygon fill convention; final
    output still uses half-open intervals for scientific overlap scoring.
    """
    _dimensions(width, height)
    if not isinstance(vertices, list) or len(vertices) < 3:
        raise ValueError("Evaluation polygon has insufficient vertices")
    points: list[tuple[float, float]] = []
    for pair in vertices:
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError("Invalid evaluation polygon point")
        x, y = pair
        if (
            type(x) not in (int, float)
            or type(y) not in (int, float)
            or not isfinite(x)
            or not isfinite(y)
            or not (0 <= x <= width and 0 <= y <= height)
        ):
            raise ValueError("Evaluation polygon point lies beyond image bounds")
        points.append((float(x), float(y)))
    if points[0] == points[-1]:
        points.pop()
    if len(set(points)) < 3:
        raise ValueError("Evaluation polygon is degenerate")
    # Polygon self-intersection must be checked by the holdout validator.
    result = Image.new("L", (width, height), 0)
    ImageDraw.Draw(result).polygon(points, fill=255)
    return binary_mask_to_runs(result, width=width, height=height)


def make_scored_mask(
    runs: tuple[tuple[int, int, int], ...],
    *,
    image_id: str,
    class_id: str,
    score: float,
    width: int,
    height: int,
) -> ScoredInstanceMask:
    """Attach verified source-pixel geometry to class and image identity."""
    return ScoredInstanceMask(image_id, class_id, score, width, height, runs)
