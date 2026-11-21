"""Read-only image signal measurements for acquisition review."""

from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal

from PIL import Image

from reefvision.config import Settings
from reefvision.domain.errors import ValidationError
from reefvision.storage.projects import resolve_managed_project_path

ANALYSIS_LONG_EDGE = 512
_STRIP_ROWS = 128
_UNSUPPORTED_LUMINANCE_MODES = {"F", "I", "I;16", "I;16B", "I;16L", "I;16N"}
ReadStatus = Literal[
    "measured",
    "unavailable",
    "checksum_mismatch",
    "dimensions_changed",
    "unsupported_luminance_mode",
    "no_visible_pixels",
]


@dataclass(frozen=True, slots=True)
class AcquisitionPixels:
    status: ReadStatus
    source_sha256: str | None = None
    decoded_pixels_sha256: str | None = None
    dark_fraction: float | None = None
    bright_fraction: float | None = None
    sharpness: float | None = None
    sharpness_width_px: int | None = None
    sharpness_height_px: int | None = None
    opaque_sample_count: int = 0


def acquisition_image_path(settings: Settings, path: str | None) -> Path | None:
    if not path:
        return None
    try:
        source = resolve_managed_project_path(settings, path)
        return source if source.is_file() else None
    except (OSError, ValidationError):
        return None


def _sharpness(luminance: Image.Image, alpha: Image.Image) -> tuple[float | None, int, int]:
    """Mean squared four-neighbor Laplacian in an opaque 8-bit luma image."""
    width, height = luminance.size
    values, opacity = luminance.tobytes(), alpha.tobytes()
    count, total = 0, 0
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            i = y * width + x
            neighbors = (i - 1, i + 1, i - width, i + width)
            if opacity[i] != 255 or any(opacity[j] != 255 for j in neighbors):
                continue
            laplacian = 4 * values[i] - sum(values[j] for j in neighbors)
            total += laplacian**2
            count += 1
    return (total / count if count else None), width, height


def measure_acquisition_pixels(
    source: Path | None,
    *,
    expected_sha256: str | None,
    dimensions: tuple[int, int],
    dark_luma_max: int,
    bright_luma_min: int,
    check_cancelled: Callable[[], None],
) -> AcquisitionPixels:
    if source is None:
        return AcquisitionPixels("unavailable")
    try:
        with source.open("rb") as stream:
            checksum = sha256()
            for chunk_index, chunk in enumerate(iter(lambda: stream.read(1024 * 1024), b"")):
                if chunk_index % 128 == 0:
                    check_cancelled()
                checksum.update(chunk)
            source_hash = checksum.hexdigest()
            if source_hash != expected_sha256:
                return AcquisitionPixels("checksum_mismatch", source_hash)
            stream.seek(0)
            with Image.open(stream) as original:
                if original.size != dimensions:
                    return AcquisitionPixels("dimensions_changed", source_hash)
                if original.mode in _UNSUPPORTED_LUMINANCE_MODES:
                    return AcquisitionPixels("unsupported_luminance_mode", source_hash)
                # Pixel duplicates use dimensions and all decoded RGBA bytes.
                # Container metadata and the filename are deliberately absent.
                width, height = original.size
                pixels_digest = sha256(f"RGBA-v1:{width}x{height}:".encode("ascii"))
                histogram = [0] * 256
                for y in range(0, height, _STRIP_ROWS):
                    if y % (_STRIP_ROWS * 8) == 0:
                        check_cancelled()
                    strip = original.crop((0, y, width, min(y + _STRIP_ROWS, height)))
                    rgba = strip.convert("RGBA")
                    pixels_digest.update(rgba.tobytes())
                    visible = rgba.getchannel("A").point([0] * 255 + [255], mode="1")
                    for level, count in enumerate(rgba.convert("L").histogram(mask=visible)):
                        histogram[level] += count
                decoded_hash = pixels_digest.hexdigest()
                total = sum(histogram)
                if not total:
                    return AcquisitionPixels("no_visible_pixels", source_hash, decoded_hash)
                # Only the sharpness score is reduced to the fixed analysis scale.
                scale = min(1.0, ANALYSIS_LONG_EDGE / max(width, height))
                size = (max(1, round(width * scale)), max(1, round(height * scale)))
                # Shrink separate luma and alpha planes to limit memory use.
                preview_luma = original.convert("L").resize(size, Image.Resampling.BOX)
                preview_alpha = (
                    original.getchannel("A").resize(size, Image.Resampling.BOX)
                    if "A" in original.getbands()
                    else Image.new("L", size, 255)
                    if "transparency" not in original.info
                    else original.convert("RGBA").getchannel("A").resize(size, Image.Resampling.BOX)
                )
                sharpness, score_width, score_height = _sharpness(preview_luma, preview_alpha)
                return AcquisitionPixels(
                    "measured",
                    source_sha256=source_hash,
                    decoded_pixels_sha256=decoded_hash,
                    dark_fraction=sum(histogram[: dark_luma_max + 1]) / total,
                    bright_fraction=sum(histogram[bright_luma_min:]) / total,
                    sharpness=sharpness,
                    sharpness_width_px=score_width,
                    sharpness_height_px=score_height,
                    opaque_sample_count=total,
                )
    except (OSError, ValueError, Image.DecompressionBombError):
        return AcquisitionPixels("unavailable")
