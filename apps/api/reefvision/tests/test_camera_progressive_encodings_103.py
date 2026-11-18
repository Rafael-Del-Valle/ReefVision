"""Camera JPEG encoding variants retain immutable originals and scientific pixel grids.

Synthetic baseline/progressive JPEG coverage complements (not replaces) physical
Sony/Canon files and installed WebView2 acceptance before a 1.0.3 release.
"""

from __future__ import annotations

import hashlib

import pytest
from PIL import Image

from reefvision.storage.images import (
    create_browser_display,
    create_thumbnail,
    ensure_supported_extension,
    inspect_staged_image,
)


@pytest.mark.parametrize(
    ("mode", "progressive", "suffix"),
    [
        ("RGB", False, ".JPG"),
        ("RGB", True, ".jpeg"),
        ("L", True, ".JPE"),
        ("CMYK", False, ".JFIF"),
        ("CMYK", True, ".JFI"),
        ("RGB", True, ".jif"),
    ],
)
def test_camera_jpeg_encoding_variants_preserve_original_and_annotation_grid(
    tmp_path, mode: str, progressive: bool, suffix: str
) -> None:
    """A camera export must not rotate, mirror or resample raw annotation pixels."""
    original_path = tmp_path / ("DSC_0421" + suffix)
    browser_path = tmp_path / "browser.png"
    thumbnail_path = tmp_path / "thumbnail.jpg"
    exif = Image.Exif()
    exif[271] = "Synthetic Camera"
    exif[274] = 6  # EXIF display instruction, not an annotation-grid transform.
    exif[36867] = "2026:05:01 15:20:30"
    exif[36881] = "+02:00"

    source = Image.new(mode, (31, 17))
    # Asymmetric pixels catch accidental axis swaps or mirroring. JPEG is lossy,
    # so compare derived pixels with the actual decoded camera original.
    for y in range(17):
        for x in range(31):
            if mode == "L":
                pixel = (x * 7 + y * 13) % 256
            elif mode == "CMYK":
                pixel = ((x * 7) % 256, (y * 13) % 256, (x + y * 5) % 256, 20)
            else:
                pixel = ((x * 7) % 256, (y * 13) % 256, (x + y * 5) % 256)
            source.putpixel((x, y), pixel)
    source.save(
        original_path,
        format="JPEG",
        progressive=progressive,
        quality=93,
        exif=exif,
    )
    original = original_path.read_bytes()
    digest = hashlib.sha256(original).hexdigest()

    ensure_supported_extension(original_path.name)
    inspected = inspect_staged_image(original_path, digest, len(original))
    create_browser_display(original_path, browser_path)
    create_thumbnail(original_path, thumbnail_path, max_width=20, max_height=20)

    assert inspected.media_type == "image/jpeg"
    assert inspected.extension == ".jpg"
    assert inspected.sha256 == digest
    assert inspected.file_size_bytes == len(original)
    assert (inspected.width_px, inspected.height_px) == (31, 17)
    assert inspected.metadata["exif"]["Orientation"] == 6
    assert inspected.metadata["exif_orientation_qc"] == "display-transformation-not-validated"
    assert inspected.capture_timestamp is not None
    assert inspected.capture_timestamp.isoformat() == "2026-05-01T13:20:30+00:00"

    with (
        Image.open(original_path) as camera,
        Image.open(browser_path) as browser,
        Image.open(thumbnail_path) as thumbnail,
    ):
        camera.load()
        browser.load()
        thumbnail.load()
        assert bool(camera.info.get("progressive")) is progressive
        assert camera.mode == mode
        assert browser.format == "PNG"
        assert browser.size == camera.size == (31, 17)
        assert browser.convert("RGB").tobytes() == camera.convert("RGB").tobytes()
        assert browser.getexif().get(274) is None
        assert thumbnail.width > thumbnail.height
        assert thumbnail.width <= 20 and thumbnail.height <= 20
        assert thumbnail.getexif().get(274) is None

    assert original_path.read_bytes() == original
    assert hashlib.sha256(original_path.read_bytes()).hexdigest() == digest
