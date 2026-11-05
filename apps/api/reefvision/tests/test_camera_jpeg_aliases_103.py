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


@pytest.mark.parametrize("suffix", [".JPG", ".jpeg", ".JfIf"])
def test_cmyk_camera_jpeg_alias_preserves_capture_bytes(tmp_path, suffix: str) -> None:
    """CMYK JPEGs must be recognized without rewriting their source captures."""
    path = tmp_path / ("CMYK capture" + suffix)
    Image.new("CMYK", (29, 13), (10, 40, 70, 5)).save(path, format="JPEG")
    original = path.read_bytes()
    digest = hashlib.sha256(original).hexdigest()

    ensure_supported_extension(path.name)
    inspected = inspect_staged_image(path, digest, len(original))

    assert inspected.media_type == "image/jpeg"
    assert inspected.extension == ".jpg"
    assert (inspected.width_px, inspected.height_px) == (29, 13)
    assert inspected.sha256 == digest
    assert path.read_bytes() == original


@pytest.mark.parametrize("orientation", [3, 6, 8])
def test_exif_oriented_jpeg_inspection_retains_raw_pixel_dimensions(
    tmp_path, orientation: int
) -> None:
    """EXIF display rotation must not change the immutable source-pixel frame."""
    path = tmp_path / f"rotated_{orientation}.JPEG"
    exif = Image.Exif()
    exif[274] = orientation
    Image.new("RGB", (31, 17), (15, 90, 180)).save(path, format="JPEG", exif=exif)
    original = path.read_bytes()
    digest = hashlib.sha256(original).hexdigest()

    ensure_supported_extension(path.name)
    inspected = inspect_staged_image(path, digest, len(original))

    assert (inspected.width_px, inspected.height_px) == (31, 17)
    assert inspected.media_type == "image/jpeg"
    assert inspected.sha256 == digest
    with Image.open(path) as reopened:
        assert reopened.getexif().get(274) == orientation
    assert path.read_bytes() == original


@pytest.mark.parametrize("suffix", [".JPG", ".jpeg", ".JFIF"])
def test_camera_jpeg_without_timezone_does_not_invent_utc_capture_time(
    tmp_path, suffix: str
) -> None:
    """A camera-local EXIF exposure time is not a verified UTC instant."""
    path = tmp_path / ("untimed_camera_capture" + suffix)
    exif = Image.Exif()
    exif[36867] = "2026:04:03 14:25:30"
    Image.new("RGB", (37, 21), (12, 34, 56)).save(path, format="JPEG", exif=exif)
    original = path.read_bytes()
    digest = hashlib.sha256(original).hexdigest()

    ensure_supported_extension(path.name)
    inspected = inspect_staged_image(path, digest, len(original))

    assert inspected.capture_timestamp is None
    assert inspected.media_type == "image/jpeg"
    assert inspected.extension == ".jpg"
    assert (inspected.width_px, inspected.height_px) == (37, 21)
    assert inspected.sha256 == digest
    assert path.read_bytes() == original


@pytest.mark.parametrize("suffix", [".JPG", ".jpeg", ".JFIF"])
def test_camera_local_exposure_reports_uncertainty_without_discarding_exif(
    tmp_path, suffix: str
) -> None:
    """A local exposure time remains provenance, not a fabricated UTC instant."""
    path = tmp_path / ("local_exposure" + suffix)
    exif = Image.Exif()
    exif[36867] = "2026:04:03 14:25:30"
    Image.new("RGB", (37, 21), (12, 34, 56)).save(path, format="JPEG", exif=exif)
    original = path.read_bytes()

    inspected = inspect_staged_image(path, hashlib.sha256(original).hexdigest(), len(original))

    assert inspected.capture_timestamp is None
    assert inspected.metadata["capture_time_warning"] == (
        "EXIF camera-local exposure time has no UTC offset; UTC capture timestamp not inferred"
    )
    assert inspected.metadata["exif"]["DateTimeOriginal"] == "2026:04:03 14:25:30"
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    ("suffix", "offset", "expected_utc"),
    [
        (".JPG", "+02:30", "2026-04-03T11:55:30+00:00"),
        (".jpeg", "-04:00", "2026-04-03T18:25:30+00:00"),
        (".JFIF", "+00:00", "2026-04-03T14:25:30+00:00"),
    ],
)
def test_camera_exif_explicit_offset_converts_to_utc_without_rewriting_capture(
    tmp_path, suffix: str, offset: str, expected_utc: str
) -> None:
    """Only explicit exposure offsets justify a UTC acquisition timestamp."""
    path = tmp_path / ("offset_exposure" + suffix)
    exif = Image.Exif()
    exif[36867] = "2026:04:03 14:25:30"
    exif[36881] = offset
    Image.new("RGB", (37, 21), (12, 34, 56)).save(path, format="JPEG", exif=exif)
    original = path.read_bytes()
    digest = hashlib.sha256(original).hexdigest()

    inspected = inspect_staged_image(path, digest, len(original))

    assert inspected.capture_timestamp is not None
    assert inspected.capture_timestamp.isoformat() == expected_utc
    assert inspected.sha256 == digest
    assert inspected.media_type == "image/jpeg"
    assert inspected.extension == ".jpg"
    assert inspected.metadata["exif"]["DateTimeOriginal"] == "2026:04:03 14:25:30"
    assert path.read_bytes() == original
