"""Real JPEG byte streams must import under supported camera filename aliases.

The original capture is immutable: extension case and alternate JPEG suffixes
must not alter pixel decoding, canonical media type, or the original bytes.
"""

from __future__ import annotations

import hashlib

import pytest
from PIL import Image

from reefvision.storage.images import (
    InvalidImageError,
    ensure_supported_extension,
    inspect_staged_image,
)


@pytest.mark.parametrize(
    "suffix",
    [".jpg", ".JPG", ".jpeg", ".JPEG", ".jpe", ".JPE", ".jfif", ".JFIF", ".jfi", ".jif"],
)
def test_jpeg_camera_filename_aliases_preserve_original(tmp_path, suffix: str) -> None:
    path = tmp_path / ("camera_capture" + suffix)
    Image.new("RGB", (17, 11), (35, 80, 125)).save(path, format="JPEG")
    original = path.read_bytes()
    digest = hashlib.sha256(original).hexdigest()

    ensure_supported_extension(path.name)
    result = inspect_staged_image(path, digest, len(original))

    assert result.sha256 == digest
    assert (result.width_px, result.height_px) == (17, 11)
    assert result.media_type == "image/jpeg"
    assert result.extension == ".jpg"
    assert result.file_size_bytes == len(original)
    assert path.read_bytes() == original


@pytest.mark.parametrize("suffix", [".jpg", ".JPEG", ".jfif"])
def test_jpeg_suffix_does_not_make_invalid_camera_bytes_valid(tmp_path, suffix: str) -> None:
    path = tmp_path / ("invalid_capture" + suffix)
    original = b"not a jpeg camera file"
    path.write_bytes(original)
    ensure_supported_extension(path.name)

    with pytest.raises(InvalidImageError):
        inspect_staged_image(path, hashlib.sha256(original).hexdigest(), len(original))

    assert path.read_bytes() == original
