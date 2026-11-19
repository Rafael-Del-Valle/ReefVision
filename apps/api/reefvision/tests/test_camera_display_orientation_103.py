"""Browser display must preserve raw scientific pixel coordinates for EXIF JPEGs.

Synthetic fixtures cannot replace physical camera / installed WebView2 acceptance.
"""

from __future__ import annotations

import hashlib

import pytest
from PIL import Image

from reefvision.storage.images import create_browser_display


@pytest.mark.parametrize("orientation", [1, 2, 3, 4, 5, 6, 7, 8])
def test_browser_display_does_not_exif_rotate_camera_pixels(tmp_path, orientation: int) -> None:
    source = tmp_path / f"camera_{orientation}.JPG"
    display = tmp_path / f"display_{orientation}.png"
    exif = Image.Exif()
    exif[274] = orientation

    # Distinct asymmetric corner colors make a silent 90/180-degree
    # rotation detectable, unlike a solid-color test fixture.
    pixels = Image.new("RGB", (19, 11), (30, 30, 30))
    pixels.putpixel((0, 0), (255, 0, 0))
    pixels.putpixel((18, 0), (0, 255, 0))
    pixels.putpixel((0, 10), (0, 0, 255))
    pixels.putpixel((18, 10), (255, 255, 0))
    pixels.save(source, format="JPEG", quality=95, exif=exif)
    original = source.read_bytes()
    original_hash = hashlib.sha256(original).hexdigest()

    create_browser_display(source, display)

    with Image.open(source) as camera, Image.open(display) as rendered:
        camera.load()
        rendered.load()
        assert rendered.format == "PNG"
        assert rendered.size == camera.size == (19, 11)
        # Compare decoded pixels, not JPEG source colors, which may differ
        # from their pre-compression fixture values.
        assert rendered.convert("RGB").tobytes() == camera.convert("RGB").tobytes()
        assert rendered.getexif().get(274) in (None, 1)
    assert source.read_bytes() == original
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash


@pytest.mark.parametrize("orientation", [1, 2, 3, 4, 5, 6, 7, 8])
@pytest.mark.parametrize("mode", ["CMYK", "L"])
def test_non_rgb_camera_jpeg_displays_without_reorienting_or_changing_original(
    tmp_path, mode: str, orientation: int
) -> None:
    """Browser PNG fallback must preserve raw axes for CMYK/grayscale camera JPEGs."""
    source = tmp_path / f"{mode.lower()}_camera_{orientation}.JPEG"
    display = tmp_path / f"{mode.lower()}_display_{orientation}.png"
    exif = Image.Exif()
    exif[274] = orientation
    pixels = Image.new(mode, (27, 13))
    corner = (0, 255, 255, 0) if mode == "CMYK" else 240
    pixels.paste(corner, (0, 0, 8, 5))
    pixels.save(source, format="JPEG", quality=95, exif=exif)
    original = source.read_bytes()
    digest = hashlib.sha256(original).hexdigest()

    create_browser_display(source, display)

    with Image.open(source) as camera, Image.open(display) as rendered:
        camera.load()
        rendered.load()
        assert rendered.format == "PNG"
        assert rendered.size == camera.size == (27, 13)
        # JPEG compression is lossy; compare against its decoded source
        # pixels instead of the original uncompressed synthetic color.
        assert rendered.convert("RGB").tobytes() == camera.convert("RGB").tobytes()
        assert rendered.getexif().get(274) in (None, 1)
    assert source.read_bytes() == original
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
