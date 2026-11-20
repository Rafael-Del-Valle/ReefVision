"""Raw-axis RGB8 rendering and a separate verified rendition cache."""

from __future__ import annotations

import hashlib
import struct
import zlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image

from reefvision.config import Settings
from reefvision.db.models.image import ImageAsset
from reefvision.domain.errors import ConflictError, ValidationError
from reefvision.schemas.image_adjustments_v18 import PhotometricParameters
from reefvision.storage.images import (
    _replace_rendition,
    _unique_rendition_temporary,
    original_bytes_match,
)
from reefvision.storage.projects import resolve_managed_project_path

MAX_SOURCE_PIXELS = 24_000_000
MAX_SOURCE_BYTES = 100 * 1024 * 1024


@dataclass(frozen=True)
class AdjustmentRendition:
    png: bytes
    rendition_sha256: str
    rgb_sha256: str


def verify_original(settings: Settings, image: ImageAsset) -> Path:
    path = resolve_managed_project_path(settings, image.managed_path)
    try:
        matches = original_bytes_match(path, image.file_size_bytes, image.sha256)
    except OSError as exc:
        raise ConflictError("The managed original image is unavailable") from exc
    if not matches:
        raise ConflictError("The managed original image no longer matches its source checksum")
    return path


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(data, zlib.crc32(kind))
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def _canonical_png(rgb: bytes, width: int, height: int) -> bytes:
    """Use filter 0 and stored deflate blocks so encoder builds cannot change bytes."""
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    row_bytes = width * 3
    block_size = 65535
    # IDAT chunks can split one deflate stream. Keep a bounded staging buffer
    # and avoid a second complete copy of the uncompressed scanlines.
    checksum = 1
    pending = bytearray()
    result = BytesIO()
    result.write(b"\x89PNG\r\n\x1a\n")
    result.write(_png_chunk(b"IHDR", header))
    result.write(_png_chunk(b"IDAT", b"\x78\x01"))
    for offset in range(0, row_bytes * height, row_bytes):
        pending.append(0)
        pending.extend(rgb[offset : offset + row_bytes])
        flushed = 0
        while len(pending) - flushed > block_size:
            block = pending[flushed : flushed + block_size]
            checksum = zlib.adler32(block, checksum)
            result.write(_png_chunk(b"IDAT", b"\x00\xff\xff\x00\x00" + block))
            flushed += block_size
        if flushed:
            del pending[:flushed]
    checksum = zlib.adler32(pending, checksum)
    length = len(pending)
    result.write(
        _png_chunk(
            b"IDAT",
            struct.pack("<BHH", 1, length, length ^ 0xFFFF) + pending + struct.pack(">I", checksum),
        )
    )
    result.write(_png_chunk(b"IEND", b""))
    return result.getvalue()


def render_adjustment(
    original: bytes,
    original_sha256: str,
    width: int,
    height: int,
    parameters: PhotometricParameters,
) -> AdjustmentRendition:
    if (
        len(original) > MAX_SOURCE_BYTES
        or width <= 0
        or height <= 0
        or width * height > MAX_SOURCE_PIXELS
    ):
        raise ValidationError("Image adjustments support at most 24 megapixels and 100 MiB")
    if hashlib.sha256(original).hexdigest() != original_sha256:
        raise ConflictError("The managed original image no longer matches its source checksum")
    table = []
    for gain in (
        parameters.red_gain_percent,
        parameters.green_gain_percent,
        parameters.blue_gain_percent,
    ):
        for value in range(256):
            shifted = (value * gain + 50) // 100 - 128
            adjusted = (
                (shifted * parameters.contrast_percent + 50) // 100
                + 128
                + parameters.brightness_offset
            )
            table.append(max(0, min(255, adjusted)))
    try:
        with Image.open(BytesIO(original)) as source:
            if source.size != (width, height):
                raise ConflictError(
                    "Decoded original dimensions no longer match the pinned source grid"
                )
            if (
                source.format not in {"JPEG", "PNG", "WEBP", "BMP"}
                or source.mode != "RGB"
                or getattr(source, "n_frames", 1) != 1
            ):
                raise ValidationError(
                    "Image adjustments require a single 8-bit RGB JPEG, PNG, WebP, or BMP"
                )
            # Do not apply EXIF transpose, ICC conversion, resampling or cropping.
            with source.point(table) as corrected:
                rgb = corrected.tobytes()
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ValidationError("The original could not be decoded as a supported RGB still") from exc
    png = _canonical_png(rgb, width, height)
    return AdjustmentRendition(
        png, hashlib.sha256(png).hexdigest(), hashlib.sha256(rgb).hexdigest()
    )


def render_managed_adjustment(
    settings: Settings, image: ImageAsset, parameters: PhotometricParameters
) -> AdjustmentRendition:
    if (
        image.file_size_bytes > MAX_SOURCE_BYTES
        or image.width_px * image.height_px > MAX_SOURCE_PIXELS
    ):
        raise ValidationError("Image adjustments support at most 24 megapixels and 100 MiB")
    path = resolve_managed_project_path(settings, image.managed_path)
    try:
        with path.open("rb") as handle:
            original = handle.read(MAX_SOURCE_BYTES + 1)
    except OSError as exc:
        raise ConflictError("The managed original image is unavailable") from exc
    if len(original) != image.file_size_bytes:
        raise ConflictError("The managed original image no longer matches its source size")
    return render_adjustment(original, image.sha256, image.width_px, image.height_px, parameters)


def adjustment_cache_path(settings: Settings, project_root: str, digest: str) -> Path:
    return resolve_managed_project_path(settings, f"{project_root}/images/adjustments/{digest}.png")


def verify_cached_rendition(path: Path, digest: str) -> bool:
    try:
        with path.open("rb") as handle:
            if hashlib.file_digest(handle, "sha256").hexdigest() != digest:
                raise ConflictError(
                    "The cached adjusted image no longer matches its pinned rendition checksum"
                )
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ConflictError("The cached adjusted image cannot be read") from exc
    return True


def publish_adjusted_rendition(path: Path, rendition: AdjustmentRendition) -> None:
    if verify_cached_rendition(path, rendition.rendition_sha256):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = _unique_rendition_temporary(path)
    try:
        temporary.write_bytes(rendition.png)
        _replace_rendition(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
