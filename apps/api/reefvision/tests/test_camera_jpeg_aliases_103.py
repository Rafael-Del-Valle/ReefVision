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
    ("orphan_tag", "orphan_value", "tag_name"),
    [
        (36881, "+00:00", "OffsetTimeOriginal"),
        (37521, "123", "SubsecTimeOriginal"),
    ],
)
def test_orphaned_camera_exposure_exif_reports_uncertain_capture_time(
    tmp_path, orphan_tag: int, orphan_value: str, tag_name: str
) -> None:
    """An offset/fraction alone cannot authenticate a camera exposure instant."""
    path = tmp_path / "orphaned_exposure.JPG"
    exif = Image.Exif()
    exif[306] = "2026:04:04 18:00:00"  # Later file-modification time.
    exif[orphan_tag] = orphan_value
    Image.new("RGB", (37, 21), (12, 34, 56)).save(path, format="JPEG", exif=exif)
    original = path.read_bytes()

    inspected = inspect_staged_image(path, hashlib.sha256(original).hexdigest(), len(original))

    assert inspected.capture_timestamp is None
    assert inspected.metadata["exif"][tag_name] == orphan_value
    assert (
        "offset or fractional seconds without DateTimeOriginal"
        in (inspected.metadata["capture_time_warning"])
    )
    assert "UTC capture timestamp not inferred" in inspected.metadata["capture_time_warning"]
    assert path.read_bytes() == original



@pytest.mark.parametrize(
    ("non_exposure_time_tag", "non_exposure_offset_tag", "suffix"),
    [
        (36868, 36882, ".JPG"),  # DateTimeDigitized / OffsetTimeDigitized
        (306, 36880, ".JPEG"),  # DateTime / OffsetTime
    ],
)
def test_camera_processing_dates_never_substitute_for_exposure_time(
    tmp_path, non_exposure_time_tag: int, non_exposure_offset_tag: int, suffix: str
) -> None:
    """Only DateTimeOriginal identifies acquisition, even with later offsets."""
    path = tmp_path / ("processed_not_exposed" + suffix)
    exif = Image.Exif()
    exif[non_exposure_time_tag] = "2026:04:04 18:00:00"
    exif[non_exposure_offset_tag] = "+02:00"
    Image.new("RGB", (17, 11), (25, 75, 125)).save(path, format="JPEG", exif=exif)
    original = path.read_bytes()

    inspected = inspect_staged_image(path, hashlib.sha256(original).hexdigest(), len(original))

    assert inspected.capture_timestamp is None
    assert "no DateTimeOriginal exposure time" in inspected.metadata["capture_time_warning"]
    assert inspected.media_type == "image/jpeg"
    assert inspected.sha256 == hashlib.sha256(original).hexdigest()
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    ("exposure", "offset"),
    [
        ("2026:04:03 14:25:30", "+14:01"),  # Beyond the maximum civil UTC offset.
        ("2026:04:03 14:25:30", "+0230"),  # Missing EXIF offset colon.
        ("2026:04:03 14:25:30", "+02:3"),  # Noncanonical minute width.
        ("2026:04:03 14:25:30", "+24:00"),  # Invalid civil time zone.
        ("2026:02:30 14:25:30", "+02:00"),  # Impossible calendar date.
        ("2026:4:03 14:25:30", "+02:00"),  # Noncanonical EXIF date width.
        ("0001:01:01 00:00:00", "+14:00"),  # UTC conversion underflows.
    ],
)
def test_camera_unverifiable_exif_never_fabricates_utc_exposure(
    tmp_path, exposure: str, offset: str
) -> None:
    """Camera clock/offset anomalies are QC evidence, never verified acquisition."""
    path = tmp_path / "camera_clock_qc.JPG"
    exif = Image.Exif()
    exif[36867] = exposure
    exif[36881] = offset
    Image.new("RGB", (23, 17), (30, 65, 115)).save(path, format="JPEG", exif=exif)
    original = path.read_bytes()
    digest = hashlib.sha256(original).hexdigest()

    inspected = inspect_staged_image(path, digest, len(original))

    assert inspected.capture_timestamp is None
    assert inspected.metadata["exif"]["DateTimeOriginal"] == exposure
    assert inspected.metadata["exif"]["OffsetTimeOriginal"] == offset
    assert "UTC capture timestamp not inferred" in inspected.metadata["capture_time_warning"]
    assert inspected.sha256 == digest
    assert (inspected.width_px, inspected.height_px) == (23, 17)
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


@pytest.mark.parametrize(
    ("suffix", "subseconds", "expected_utc", "precision_warning"),
    [
        (".JPG", "123", "2026-04-03T11:55:30.123000+00:00", False),
        (".jpeg", "123456789", "2026-04-03T11:55:30.123456+00:00", True),
    ],
)
def test_real_camera_jpeg_fractional_exposure_preserves_qc_and_source(
    tmp_path, suffix: str, subseconds: str, expected_utc: str, precision_warning: bool
) -> None:
    """Preserve subsecond acquisition precision without rewriting source JPEGs."""
    path = tmp_path / ("fractional_exposure" + suffix)
    exif = Image.Exif()
    exif[36867] = "2026:04:03 14:25:30"
    exif[36881] = "+02:30"
    exif[37521] = subseconds
    Image.new("RGB", (23, 17), (30, 65, 115)).save(path, format="JPEG", exif=exif)
    original = path.read_bytes()
    digest = hashlib.sha256(original).hexdigest()

    inspected = inspect_staged_image(path, digest, len(original))

    assert inspected.capture_timestamp is not None
    assert inspected.capture_timestamp.isoformat() == expected_utc
    assert inspected.metadata["exif"]["SubsecTimeOriginal"] == subseconds
    if precision_warning:
        assert "exceeds microsecond precision" in inspected.metadata[
            "capture_time_precision_warning"
        ]
    else:
        assert "capture_time_precision_warning" not in inspected.metadata
    assert inspected.sha256 == digest
    assert inspected.extension == ".jpg"
    assert inspected.media_type == "image/jpeg"
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    ("nested_override", "conflict_field"),
    [
        ({36867: "2026:10:02 12:30:00"}, "DateTimeOriginal"),
        ({36881: "+01:00"}, "OffsetTimeOriginal"),
        ({37521: "999"}, "SubsecTimeOriginal"),
        # Real camera EXIF decoders may expose the *same* ASCII exposure
        # field as NUL-padded bytes in ExifIFD and as text in IFD0.
        # That representation difference must not erase a verified UTC time.
        ({36867: b"2026:10:01 12:30:00\x00"}, None),
        ({36881: b"-04:00\x00"}, None),
        ({37521: b"123\x00"}, None),
        # Decoding to comparable text must still reject actual conflicts
        # and undecodable vendor values, never fabricated camera instants.
        ({36867: b"2026:10:02 12:30:00\x00"}, "DateTimeOriginal"),
        ({36881: b"+01:00\x00"}, "OffsetTimeOriginal"),
        ({37521: b"999\x00"}, "SubsecTimeOriginal"),
        ({36867: b"\xff"}, "DateTimeOriginal"),
        ({}, None),
    ],
)
def test_camera_import_never_promotes_conflicting_ifd0_exposure_to_utc(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    nested_override: dict[int, str | bytes],
    conflict_field: str | None,
) -> None:
    """Inconsistent camera IFDs remain read-only QC evidence, not UTC observations."""
    path = tmp_path / "DSC_CONFLICT.JPEG"
    Image.new("RGB", (23, 17), (30, 65, 115)).save(path, format="JPEG")
    original = path.read_bytes()
    top_tags = {
        36867: "2026:10:01 12:30:00",
        36881: "-04:00",
        37521: "123",
    }
    nested_tags = {**top_tags, **nested_override}
    original_getexif = Image.Image.getexif
    original_get_ifd = Image.Exif.get_ifd

    def camera_getexif(image: Image.Image) -> Image.Exif:
        exif = original_getexif(image)
        exif.update(top_tags)
        return exif

    def camera_get_ifd(exif: Image.Exif, tag: int):
        if tag == 34665:
            return nested_tags
        return original_get_ifd(exif, tag)

    with monkeypatch.context() as patch:
        patch.setattr(Image.Image, "getexif", camera_getexif)
        patch.setattr(Image.Exif, "get_ifd", camera_get_ifd)
        inspected = inspect_staged_image(path, hashlib.sha256(original).hexdigest(), len(original))

    assert inspected.sha256 == hashlib.sha256(original).hexdigest()
    assert inspected.media_type == "image/jpeg"
    assert (inspected.width_px, inspected.height_px) == (23, 17)
    if conflict_field is None:
        assert inspected.capture_timestamp is not None
        assert inspected.capture_timestamp.isoformat() == "2026-10-01T16:30:00.123000+00:00"
        assert "exif_exposure_ifd_conflict_fields" not in inspected.metadata
    else:
        assert inspected.capture_timestamp is None
        assert inspected.metadata["exif_exposure_ifd_conflict_fields"] == [conflict_field]
        assert "UTC capture timestamp not inferred" in inspected.metadata["capture_time_warning"]
    assert path.read_bytes() == original
