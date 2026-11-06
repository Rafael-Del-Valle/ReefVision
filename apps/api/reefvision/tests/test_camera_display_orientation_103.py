"""Browser display must preserve raw scientific pixel coordinates for EXIF JPEGs.

Synthetic fixtures cannot replace physical camera / installed WebView2 acceptance.
"""

from __future__ import annotations

import hashlib

import pytest
from PIL import Image

from reefvision.storage.images import create_browser_display


@pytest.mark.parametrize("orientation", [1, 3, 6, 8])
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
