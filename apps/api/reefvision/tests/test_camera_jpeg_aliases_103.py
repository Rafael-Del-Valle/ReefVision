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


@pytest.mark.parametrize("filename", ["DSC 0001.JPG", "échantillon_01.JPEG", "coral.sample.JpEg"])
def test_camera_jpeg_aliases_accept_realistic_unicode_and_dotted_names(
    tmp_path, filename: str
) -> None:
    """Filename normalization must not rewrite or corrupt the source capture."""
    path = tmp_path / filename
    Image.new("RGB", (23, 19), (17, 88, 143)).save(path, format="JPEG")
    original = path.read_bytes()
    digest = hashlib.sha256(original).hexdigest()

    ensure_supported_extension(path.name)
    inspected = inspect_staged_image(path, digest, len(original))

    assert inspected.extension == ".jpg"
    assert inspected.media_type == "image/jpeg"
    assert (inspected.width_px, inspected.height_px) == (23, 19)
    assert inspected.sha256 == digest
    assert path.name == filename
    assert path.read_bytes() == original
