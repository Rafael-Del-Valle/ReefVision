"""Safe managed image and thumbnail filesystem operations."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

from PIL import ExifTags, Image, ImageOps, UnidentifiedImageError

from reefvision.config import Settings
from reefvision.domain.errors import ValidationError
from reefvision.storage.projects import resolve_managed_project_path

# File extensions are only a preflight filter; Pillow verifies the actual decoded format.
SUPPORTED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".jpe",
    ".jfif",
    ".jfi",
    ".jif",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
    ".bmp",
    ".dib",
    ".gif",
}
FORMAT_DETAILS = {
    "JPEG": (".jpg", "image/jpeg"),
    "PNG": (".png", "image/png"),
    "TIFF": (".tiff", "image/tiff"),
    "WEBP": (".webp", "image/webp"),
    "BMP": (".bmp", "image/bmp"),
    "GIF": (".gif", "image/gif"),
}


class UnsupportedImageError(ValueError):
    """File extension or decoded format is outside Milestone 2 support."""


class InvalidImageError(ValueError):
    """The file cannot be decoded as a valid image."""


@dataclass(frozen=True)
class InspectedImage:
    sha256: str
    width_px: int
    height_px: int
    file_size_bytes: int
    media_type: str
    extension: str
    metadata: dict[str, Any]
    capture_timestamp: datetime | None


def project_image_directories(settings: Settings, project_storage_root: str) -> dict[str, Path]:
    root = resolve_managed_project_path(settings, project_storage_root)
    directories = {
        "originals": root / "images" / "originals",
        "thumbnails": root / "images" / "thumbnails",
        "staging": root / ".imports",
    }
    for directory in directories.values():
        directory.mkdir(parents=True, exist_ok=True)
    return directories


def safe_original_name(filename: str | None) -> str:
    if not filename:
        return "unnamed-image"
    return Path(filename.replace("\\", "/")).name or "unnamed-image"


def ensure_supported_extension(filename: str) -> None:
    if Path(filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise UnsupportedImageError("Supported image types are JPEG, PNG, TIFF, WebP, BMP, and GIF")


def stream_to_staging(source: BinaryIO, destination: Path) -> tuple[str, int]:
    """Write a staged file completely, fsync it, and return checksum and byte count."""

    digest = hashlib.sha256()
    total = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        with destination.open("xb") as output:
            created = True
            while chunk := source.read(1024 * 1024):
                output.write(chunk)
                digest.update(chunk)
                total += len(chunk)
            output.flush()
            os.fsync(output.fileno())
    except Exception:
        # Exclusive creation may fail because another upload already owns
        # this UUID path. Never delete a file that this call did not create.
        if created:
            destination.unlink(missing_ok=True)
        raise
    return digest.hexdigest(), total


def _json_safe(value: object) -> object | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return str(value) if not isinstance(value, bytes) else None


def _capture_timestamp(exif: dict[int, Any]) -> datetime | None:
    # Camera-local EXIF timestamps may include explicit UTC offsets and
    # subsecond tags. Pair each date with its own offset and fractional time;
    # never borrow either from a different acquisition field.
    for key, offset_key, subsec_key in (
        (36867, 36881, 37521),
        (36868, 36882, 37522),
        (306, 36880, 37520),
    ):
        raw = exif.get(key)
        if raw is None:
            continue
        # A present but malformed exposure timestamp is not evidence that a
        # later digitization or file-modification timestamp is the exposure.
        # Some camera libraries return ASCII EXIF values as bytes.
        if isinstance(raw, bytes):
            try:
                raw = raw.decode("ascii").rstrip("\x00")
            except UnicodeDecodeError:
                return None
        if not isinstance(raw, str):
            return None
        offset = exif.get(offset_key)
        if isinstance(offset, bytes):
            try:
                offset = offset.decode("ascii").rstrip("\x00")
            except UnicodeDecodeError:
                return None
        if offset is not None and not isinstance(offset, str):
            return None
        try:
            if isinstance(offset, str) and offset:
                timestamp = datetime.strptime(raw + offset, "%Y:%m:%d %H:%M:%S%z").astimezone(UTC)
            else:
                # Preserve the existing legacy behavior for offset-free images.
                timestamp = datetime.strptime(raw, "%Y:%m:%d %H:%M:%S").replace(tzinfo=UTC)
        except ValueError:
            # Do not silently substitute DateTimeDigitized/DateTime when a
            # higher-priority acquisition field exists but cannot be trusted.
            return None

        fraction = exif.get(subsec_key)
        if isinstance(fraction, bytes):
            try:
                fraction = fraction.decode("ascii")
            except UnicodeDecodeError:
                fraction = None
        if isinstance(fraction, str) and fraction.isascii() and fraction.isdigit():
            # Datetimes represent microseconds; preserve the unmodified raw
            # EXIF string in metadata when cameras record finer precision.
            timestamp = timestamp.replace(microsecond=int(fraction[:6].ljust(6, "0")))
        return timestamp
    return None


def inspect_staged_image(path: Path, sha256: str, file_size_bytes: int) -> InspectedImage:
    try:
        with Image.open(path) as image:
            decoded_format = image.format
            image.verify()
        if decoded_format not in FORMAT_DETAILS:
            raise UnsupportedImageError("Decoded image format is not supported")
        extension, media_type = FORMAT_DETAILS[decoded_format]
        with Image.open(path) as image:
            width, height = image.size
            if width <= 0 or height <= 0:
                raise InvalidImageError("Image dimensions must be greater than zero")
            # A valid container/header does not guarantee decodable pixels:
            # TIFF, BMP, and GIF can pass verify() with truncated image data.
            # Never commit a scientific image that cannot produce a rendition.
            if decoded_format == "GIF" and getattr(image, "n_frames", 1) != 1:
                raise UnsupportedImageError(
                    "Animated GIFs cannot be safely imported as a single scientific image"
                )
            if decoded_format == "TIFF" and getattr(image, "n_frames", 1) != 1:
                raise UnsupportedImageError(
                    "Multi-page TIFFs cannot be safely imported as a single scientific image"
                )
            image.load()
            image_exif = image.getexif()
            exif = dict(image_exif)
            # Real cameras normally store DateTimeOriginal and OffsetTimeOriginal
            # in the nested Exif IFD. The top-level dict contains only its offset.
            exif.update(image_exif.get_ifd(ExifTags.IFD.Exif))
            named_exif = {
                ExifTags.TAGS.get(key, str(key)): _json_safe(value)
                for key, value in exif.items()
                if _json_safe(value) is not None
            }
            safe_info = {
                str(key): converted
                for key, value in image.info.items()
                if (converted := _json_safe(value)) is not None
            }
            metadata: dict[str, Any] = {
                "format": decoded_format,
                "mode": image.mode,
                "info": safe_info,
                "exif": named_exif,
            }
            return InspectedImage(
                sha256=sha256,
                width_px=width,
                height_px=height,
                file_size_bytes=file_size_bytes,
                media_type=media_type,
                extension=extension,
                metadata=metadata,
                capture_timestamp=_capture_timestamp(exif),
            )
    except UnsupportedImageError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise InvalidImageError("File is not a readable image") from exc


def commit_staged_image(staged_path: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ValidationError("Managed image destination already exists")
    os.replace(staged_path, destination)


def create_browser_display(source: Path, destination: Path) -> None:
    """Create a browser-safe, full-resolution PNG rendition without changing the source."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.unlink(missing_ok=True)
    try:
        with Image.open(source) as image:
            # Match EXIF-oriented thumbnails without altering the camera original.
            display: Image.Image = ImageOps.exif_transpose(image)
            if display.mode not in {"1", "L", "LA", "P", "RGB", "RGBA", "I", "I;16"}:
                display = display.convert("RGB")
            display.save(temporary, format="PNG", optimize=True)
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def create_thumbnail(source: Path, destination: Path, *, max_width: int, max_height: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.unlink(missing_ok=True)
    try:
        with Image.open(source) as image:
            oriented: Image.Image = ImageOps.exif_transpose(image)
            if oriented.mode in {"I;16", "I;16L", "I;16B"}:
                oriented = oriented.point(lambda value: value / 257).convert("L")
            elif oriented.mode not in {"RGB", "L"}:
                oriented = oriented.convert("RGB")
            oriented.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
            if oriented.mode == "L":
                oriented = oriented.convert("RGB")
            oriented.save(temporary, format="JPEG", quality=85, optimize=True)
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
