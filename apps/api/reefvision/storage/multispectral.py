"""Decode a checksummed grayscale original in its declared source-pixel grid."""

from hashlib import sha256
from io import BytesIO
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from PIL import Image, UnidentifiedImageError

from reefvision.config import Settings
from reefvision.db.models.image import ImageAsset
from reefvision.domain.errors import ConflictError, ValidationError
from reefvision.storage.projects import resolve_managed_project_path

MAX_PIXELS = 4_194_304
MAX_BYTES = 48 * 1024 * 1024


def load_band(
    settings: Settings, image: ImageAsset, expected_sha256: str
) -> tuple[NDArray[np.uint16], Literal[8, 16]]:
    if image.sha256 != expected_sha256 or not image.managed_path:
        raise ConflictError("The selected band no longer matches the pinned project image")
    if image.width_px * image.height_px > MAX_PIXELS or image.file_size_bytes > MAX_BYTES:
        raise ValidationError("A spectral band supports up to 4,194,304 pixels and 48 MiB")
    path = resolve_managed_project_path(settings, image.managed_path)
    try:
        with path.open("rb") as original:
            data = original.read(MAX_BYTES + 1)
    except OSError as exc:
        raise ConflictError("Restore the missing spectral band original before replay") from exc
    if len(data) != image.file_size_bytes or sha256(data).hexdigest() != expected_sha256:
        raise ConflictError("The spectral band original failed its byte checksum")
    try:
        with Image.open(BytesIO(data)) as decoded:
            if decoded.format not in {"PNG", "TIFF"} or getattr(decoded, "n_frames", 1) != 1:
                raise ValidationError("Choose a single-plane grayscale PNG or TIFF for each band")
            if decoded.getexif().get(274, 1) != 1:
                raise ValidationError(
                    "The multispectral grid requires bands stored with top-left orientation"
                )
            if decoded.size != (image.width_px, image.height_px):
                raise ConflictError(
                    "The spectral band dimensions differ from its registered original"
                )
            bits: Literal[8, 16]
            if decoded.mode == "L":
                bits = 8
            elif decoded.mode in {"I;16", "I;16L", "I;16B"} or (
                decoded.format == "PNG" and decoded.mode == "I"
            ):
                bits = 16
            else:
                raise ValidationError(
                    "Multispectral bands require unsigned 8- or 16-bit grayscale samples"
                )
            return np.asarray(decoded, dtype=np.uint16).copy(), bits
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValidationError("The spectral band could not be decoded") from exc


def encode_rgba(pixels: NDArray[np.uint8]) -> bytes:
    result = BytesIO()
    Image.fromarray(pixels).save(result, format="PNG")
    return result.getvalue()


def encode_index(values: NDArray[np.float32]) -> bytes:
    result = BytesIO()
    Image.fromarray(values).save(result, format="TIFF")
    return result.getvalue()
