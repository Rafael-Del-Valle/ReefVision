"""Safe managed image and thumbnail filesystem operations."""

from __future__ import annotations

import contextlib
import errno
import hashlib
import os
import shutil
import struct
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

from PIL import ExifTags, Image, UnidentifiedImageError

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
        raw = raw.rstrip("\x00")
        offset = exif.get(offset_key)
        if isinstance(offset, bytes):
            try:
                offset = offset.decode("ascii").rstrip("\x00")
            except UnicodeDecodeError:
                return None
        if offset is not None and not isinstance(offset, str):
            return None
        if isinstance(offset, str):
            offset = offset.rstrip("\x00")
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
                fraction = fraction.decode("ascii").rstrip("\x00")
            except UnicodeDecodeError:
                fraction = None
        if isinstance(fraction, str):
            fraction = fraction.rstrip("\x00")
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
            # APNG and animated WebP also decode their first frame without
            # error. Importing that first frame as a still scientific image
            # would silently discard the remaining time points. Preserve the
            # entire source by rejecting multi-frame containers before commit.
            if getattr(image, "n_frames", 1) != 1:
                raise UnsupportedImageError(
                    f"Multi-frame {decoded_format} cannot be imported as a single scientific image"
                )
            image.load()
            # A valid camera JPEG can contain a damaged EXIF IFD while its
            # pixels still decode correctly. Preserve those original bytes and
            # report metadata uncertainty rather than reject a usable image.
            # Never infer exposure time from DateTime when the acquisition IFD
            # could not be read: that tag may describe a later file modification.
            exif_warning: str | None = None
            try:
                image_exif = image.getexif()
                exif = dict(image_exif)
            except (OSError, SyntaxError, ValueError, TypeError, struct.error):
                exif = {}
                exif_warning = "EXIF metadata could not be decoded; capture time is unavailable"
            else:
                try:
                    # DateTimeOriginal and OffsetTimeOriginal are typically
                    # nested, rather than exposed in the top-level EXIF dict.
                    exif.update(image_exif.get_ifd(ExifTags.IFD.Exif))
                except (OSError, SyntaxError, ValueError, TypeError, struct.error):
                    exif_warning = (
                        "Nested EXIF metadata could not be decoded; capture time is unavailable"
                    )
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
            if exif_warning is not None:
                metadata["exif_warning"] = exif_warning
            return InspectedImage(
                sha256=sha256,
                width_px=width,
                height_px=height,
                file_size_bytes=file_size_bytes,
                media_type=media_type,
                extension=extension,
                metadata=metadata,
                capture_timestamp=None if exif_warning is not None else _capture_timestamp(exif),
            )
    except UnsupportedImageError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise InvalidImageError("File is not a readable image") from exc


def commit_staged_image(staged_path: Path, destination: Path) -> None:
    """Publish an immutable original without a check-then-replace overwrite race."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Both paths are within the managed project on the same volume.
        # Creating a hard link is atomic and fails if another import already
        # owns this name; os.replace() could silently overwrite that original.
        os.link(staged_path, destination)
    except FileExistsError as exc:
        raise ValidationError("Managed image destination already exists") from exc
    except OSError as exc:
        # Some Windows removable filesystems (notably exFAT/FAT) do not
        # support hard links. Exclusively create and fsync the destination
        # instead; never fall back to an overwriting rename.
        unsupported = {
            errno.EPERM,
            errno.EACCES,
            errno.EXDEV,
            errno.ENOTSUP,
            errno.EOPNOTSUPP,
        }
        if exc.errno not in unsupported and getattr(exc, "winerror", None) not in {1, 50}:
            raise
        created = False
        try:
            with destination.open("xb") as output:
                created = True
                with staged_path.open("rb") as source:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
        except FileExistsError as collision:
            raise ValidationError("Managed image destination already exists") from collision
        except Exception:
            if created:
                destination.unlink(missing_ok=True)
            raise
    # The original has already been published. A transient failure to remove
    # its staging link must not turn a valid import into an orphaned original
    # with no database record. Retain the staging copy for later cleanup.
    with contextlib.suppress(OSError):
        staged_path.unlink()


def _unique_rendition_temporary(destination: Path) -> Path:
    """Reserve a unique sibling path for concurrent atomic rendition writes."""
    descriptor, name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".part", dir=destination.parent
    )
    os.close(descriptor)
    return Path(name)


def _replace_rendition(temporary: Path, destination: Path) -> None:
    """Publish a rendition despite brief Windows destination-file contention."""

    for attempt in range(5):
        try:
            os.replace(temporary, destination)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.01 * (2**attempt))


def create_browser_display(source: Path, destination: Path) -> None:
    """Create a browser-safe, full-resolution PNG rendition without changing the source."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = _unique_rendition_temporary(destination)
    try:
        with Image.open(source) as image:
            # Annotation coordinates and stored dimensions refer to raw camera
            # pixels. Do not EXIF-transpose the scientific display rendition.
            # Remove orientation metadata so WebView2 cannot rotate it again.
            display: Image.Image = image.copy()
            display.info.pop("exif", None)
            display.info.pop("orientation", None)
            if display.mode not in {"1", "L", "LA", "P", "RGB", "RGBA", "I", "I;16", "I;16B"}:
                display = display.convert("RGB")
            display.save(temporary, format="PNG", optimize=True)
        _replace_rendition(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def create_thumbnail(source: Path, destination: Path, *, max_width: int, max_height: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = _unique_rendition_temporary(destination)
    try:
        with Image.open(source) as image:
            # Thumbnails and scientific overlays must share the original camera
            # pixel frame, regardless of EXIF display-orientation hints.
            oriented: Image.Image = image.copy()
            oriented.info.pop("exif", None)
            oriented.info.pop("orientation", None)
            if oriented.mode in {"I;16", "I;16L", "I;16B"}:
                # Pillow cannot apply point() directly to big-/little-endian
                # 16-bit variants. Promote those pixels to integer mode first
                # without losing their original scientific source values.
                if oriented.mode != "I;16":
                    oriented = oriented.convert("I")
                oriented = oriented.point(lambda value: value / 257).convert("L")
            elif oriented.mode not in {"RGB", "L"}:
                oriented = oriented.convert("RGB")
            oriented.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
            if oriented.mode == "L":
                oriented = oriented.convert("RGB")
            oriented.save(temporary, format="JPEG", quality=85, optimize=True)
        _replace_rendition(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
