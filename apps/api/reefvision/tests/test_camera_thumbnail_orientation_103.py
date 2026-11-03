"""Thumbnails must retain the scientific camera coordinate frame.

Synthetic EXIF JPEGs complement, but do not replace, installed WebView2 and
physical-camera acceptance.
"""

from __future__ import annotations

import hashlib

import pytest
from PIL import Image

from reefvision.storage.images import create_thumbnail


@pytest.mark.parametrize("orientation", [1, 3, 6, 8])
def test_thumbnail_keeps_raw_camera_axes_and_source_bytes(tmp_path, orientation: int) -> None:
    source = tmp_path / f"camera_{orientation}.JPG"
    thumbnail = tmp_path / f"thumb_{orientation}.jpg"
    exif = Image.Exif()
    exif[274] = orientation

    # Non-square geometry distinguishes raw axes from EXIF-rotated axes.
    pixels = Image.new("RGB", (80, 40), (20, 20, 20))
    for x in range(0, 20):
        for y in range(0, 20):
            pixels.putpixel((x, y), (240, 20, 20))
    pixels.save(source, format="JPEG", quality=95, exif=exif)
    original = source.read_bytes()
    digest = hashlib.sha256(original).hexdigest()

    create_thumbnail(source, thumbnail, max_width=40, max_height=40)

    with Image.open(thumbnail) as result:
        assert result.format == "JPEG"
        assert result.size == (40, 20)
        assert result.getexif().get(274) is None
        # Lossy thumbnail compression still leaves the red top-left patch
        # visibly distinct from the neutral bottom-right background.
        red = result.convert("RGB").getpixel((4, 4))
        neutral = result.convert("RGB").getpixel((35, 15))
        assert red[0] > red[1] + 80
        assert neutral[0] < 100

    assert source.read_bytes() == original
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
