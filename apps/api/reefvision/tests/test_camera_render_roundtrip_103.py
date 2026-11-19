"""API-level camera JPEG acceptance for source-aligned scientific display.

These deterministic synthetic images complement physical Sony/Canon camera
imports and installed WebView2 validation; they do not replace either.
"""

from __future__ import annotations

import hashlib
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from reefvision.tests.test_images import create_project, import_one


@pytest.mark.parametrize(
    ("mode", "progressive", "suffix", "orientation"),
    [
        ("RGB", True, ".JPG", 2),
        ("L", False, ".JPEG", 6),
        ("CMYK", True, ".JFI", 7),
        ("CMYK", False, ".JFIF", 1),
    ],
)
def test_camera_jpeg_api_display_roundtrip_preserves_raw_annotation_pixels(
    client: TestClient,
    mode: str,
    progressive: bool,
    suffix: str,
    orientation: int,
) -> None:
    """JPEG aliases, color modes and EXIF hints must not rotate the API display."""
    project = create_project(client, f"Camera display {mode} {suffix} {orientation}")
    exif = Image.Exif()
    exif[271] = "Synthetic Camera"
    exif[274] = orientation
    camera = Image.new(mode, (47, 29))
    for y in range(camera.height):
        for x in range(camera.width):
            if mode == "L":
                color = (x * 7 + y * 13) % 256
            elif mode == "CMYK":
                color = ((x * 7) % 256, (y * 11) % 256, (x + y * 9) % 256, 20)
            else:
                color = ((x * 7) % 256, (y * 11) % 256, (x + y * 9) % 256)
            camera.putpixel((x, y), color)

    stream = BytesIO()
    camera.save(stream, format="JPEG", quality=94, progressive=progressive, exif=exif)
    original = stream.getvalue()
    digest = hashlib.sha256(original).hexdigest()

    report = import_one(
        client,
        project["id"],
        filename=f"DSC_0042{suffix}",
        content=original,
    )
    assert len(report["successful"]) == 1, report
    assert not report["failed"], report
    image_id = report["successful"][0]["image_id"]
    metadata_response = client.get(f"/api/v1/images/{image_id}")
    assert metadata_response.status_code == 200
    metadata = metadata_response.json()
    assert metadata["sha256"] == digest
    assert metadata["media_type"] == "image/jpeg"
    assert (metadata["width_px"], metadata["height_px"]) == (47, 29)
    assert metadata["metadata_json"]["exif"]["Orientation"] == orientation

    original_response = client.get(f"/api/v1/images/{image_id}/content")
    assert original_response.status_code == 200
    assert original_response.content == original

    display_response = client.get(f"/api/v1/images/{image_id}/display")
    assert display_response.status_code == 200
    assert display_response.headers["content-type"].startswith("image/png")
    with (
        Image.open(BytesIO(original)) as source,
        Image.open(BytesIO(display_response.content)) as rendered,
    ):
        source.load()
        rendered.load()
        assert source.getexif().get(274) == orientation
        assert rendered.format == "PNG"
        assert rendered.size == source.size == (47, 29)
        assert rendered.getexif().get(274) is None
        # Compare against JPEG's actual decoded pixels, not the uncompressed
        # fixture: compression must not be mistaken for a rotation defect.
        assert rendered.convert("RGB").tobytes() == source.convert("RGB").tobytes()

    # Repeated gallery viewing must reuse a stable derivative, not mutate the
    # scientific original or silently change the source coordinate frame.
    repeat = client.get(f"/api/v1/images/{image_id}/display")
    assert repeat.status_code == 200
    assert repeat.content == display_response.content
    assert client.get(f"/api/v1/images/{image_id}/content").content == original
