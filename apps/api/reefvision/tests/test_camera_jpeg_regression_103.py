"""Camera JPEG regression coverage for the consolidated 1.0.3 import path."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from reefvision.storage.images import create_browser_display, create_thumbnail
from reefvision.tests.test_images import create_project, import_one


def test_progressive_camera_jpeg_keeps_original_bytes_and_exif(
    client: TestClient,
) -> None:
    project = create_project(client, "Progressive camera JPEG")
    exif = Image.Exif()
    exif[274] = 6  # EXIF orientation: rotate 90 degrees clockwise.
    exif[306] = "2026:10:01 12:30:00"
    stream = BytesIO()
    Image.new("RGB", (64, 48), (20, 90, 120)).save(
        stream,
        format="JPEG",
        progressive=True,
        exif=exif,
        icc_profile=b"synthetic-test-icc",
    )
    payload = stream.getvalue()
    report = import_one(
        client,
        project["id"],
        filename="IMG_0001.JPEG",
        content=payload,
    )
    assert len(report["successful"]) == 1, report
    image_id = report["successful"][0]["image_id"]
    metadata = client.get(f"/api/v1/images/{image_id}").json()
    assert metadata["media_type"] == "image/jpeg"
    assert metadata["width_px"] == 64
    assert metadata["height_px"] == 48
    assert metadata["metadata_json"]["exif"]["Orientation"] == 6
    assert metadata["capture_timestamp"].startswith("2026-10-01T12:30:00")
    original = client.get(f"/api/v1/images/{image_id}/content")
    assert original.status_code == 200
    assert original.content == payload


@pytest.mark.parametrize("extension", [".jpg", ".jpeg", ".jpe", ".jfif", ".jfi", ".jif"])
def test_jpeg_camera_filename_aliases_preserve_original_content(
    client: TestClient,
    extension: str,
) -> None:
    project = create_project(client, f"Camera JPEG alias {extension}")
    stream = BytesIO()
    Image.new("RGB", (37, 29), (20, 90, 120)).save(stream, format="JPEG")
    payload = stream.getvalue()
    report = import_one(
        client, project["id"], filename=f"DSC_001{extension.upper()}", content=payload
    )
    assert len(report["successful"]) == 1, report
    image_id = report["successful"][0]["image_id"]
    metadata = client.get(f"/api/v1/images/{image_id}").json()
    assert metadata["media_type"] == "image/jpeg"
    assert (metadata["width_px"], metadata["height_px"]) == (37, 29)
    response = client.get(f"/api/v1/images/{image_id}/content")
    assert response.status_code == 200
    assert response.content == payload


@pytest.mark.parametrize("progressive", [False, True])
def test_truncated_camera_jpeg_rejected_before_import_commit(
    client: TestClient, progressive: bool
) -> None:
    project = create_project(client, "Truncated camera JPEG")
    stream = BytesIO()
    Image.new("RGB", (512, 512), (20, 30, 40)).save(stream, format="JPEG", progressive=progressive)
    truncated = stream.getvalue()[:-2]  # Remove JPEG end-of-image marker.
    report = import_one(client, project["id"], filename="DSC_0002.JPEG", content=truncated)
    assert not report["successful"], report
    assert len(report["failed"]) == 1, report


@pytest.mark.parametrize(
    ("orientation", "expected"),
    [
        (1, (64, 48)),
        (2, (64, 48)),
        (3, (64, 48)),
        (4, (64, 48)),
        (5, (48, 64)),
        (6, (48, 64)),
        (7, (48, 64)),
        (8, (48, 64)),
    ],
)
def test_camera_display_exif_orientation_preserves_original(
    tmp_path: Path, orientation: int, expected: tuple[int, int]
) -> None:
    source = tmp_path / "DSC_0042.JPEG"
    display = tmp_path / "display.png"
    exif = Image.Exif()
    exif[274] = orientation
    Image.new("RGB", (64, 48), (20, 90, 120)).save(source, format="JPEG", exif=exif)
    original = source.read_bytes()
    create_browser_display(source, display)
    with Image.open(display) as rendered:
        assert rendered.format == "PNG"
        assert rendered.size == expected
        assert rendered.getexif().get(274) is None
    assert source.read_bytes() == original
    with Image.open(source) as camera:
        assert camera.size == (64, 48)
        assert camera.getexif().get(274) == orientation


@pytest.mark.parametrize(
    ("orientation", "quadrant_order"),
    [
        (1, (0, 1, 2, 3)),
        (2, (1, 0, 3, 2)),
        (3, (3, 2, 1, 0)),
        (4, (2, 3, 0, 1)),
        (5, (0, 2, 1, 3)),
        (6, (2, 0, 3, 1)),
        (7, (3, 1, 2, 0)),
        (8, (1, 3, 0, 2)),
    ],
)
def test_camera_exif_orientation_keeps_display_and_thumbnail_pixels_aligned(
    tmp_path: Path, orientation: int, quadrant_order: tuple[int, int, int, int]
) -> None:
    """Detect incorrect mirrored/rotated camera pixels, not just swapped dimensions."""

    source = tmp_path / "DSC_0043.JPEG"
    display = tmp_path / "display.png"
    thumbnail = tmp_path / "thumbnail.jpg"
    colors = [(240, 20, 20), (20, 240, 20), (20, 20, 240), (240, 240, 20)]
    camera = Image.new("RGB", (80, 60))
    for (x, y), color in zip([(0, 0), (40, 0), (0, 30), (40, 30)], colors, strict=True):
        camera.paste(color, (x, y, x + 40, y + 30))
    exif = Image.Exif()
    exif[274] = orientation
    camera.save(source, format="JPEG", quality=100, subsampling=0, exif=exif)
    original = source.read_bytes()

    create_browser_display(source, display)
    create_thumbnail(source, thumbnail, max_width=160, max_height=160)

    expected_size = (80, 60) if orientation <= 4 else (60, 80)
    sample_points = [(0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75)]
    for rendition in (display, thumbnail):
        with Image.open(rendition) as rendered:
            assert rendered.size == expected_size
            assert rendered.getexif().get(274) is None
            for (fx, fy), color_index in zip(sample_points, quadrant_order, strict=True):
                actual = rendered.convert("RGB").getpixel(
                    (int(rendered.width * fx), int(rendered.height * fy))
                )
                expected = colors[color_index]
                assert all(abs(a - b) < 35 for a, b in zip(actual, expected, strict=True))
    assert source.read_bytes() == original


@pytest.mark.parametrize(
    ("mode", "color", "expected_display_mode"),
    [
        ("CMYK", (10, 40, 80, 5), "RGB"),
        ("L", 127, "L"),
    ],
)
def test_non_rgb_camera_jpeg_import_and_oriented_renditions(
    client: TestClient,
    tmp_path: Path,
    mode: str,
    color: tuple[int, ...] | int,
    expected_display_mode: str,
) -> None:
    """CMYK and grayscale camera JPEGs must render without altering source bytes."""

    source = tmp_path / "DSC_0003.JPEG"
    display = tmp_path / "display.png"
    thumbnail = tmp_path / "thumbnail.jpg"
    exif = Image.Exif()
    exif[274] = 6
    Image.new(mode, (80, 60), color).save(source, format="JPEG", exif=exif)
    original = source.read_bytes()

    project = create_project(client, f"{mode} camera JPEG")
    report = import_one(client, project["id"], filename=source.name, content=original)
    assert len(report["successful"]) == 1, report
    image_id = report["successful"][0]["image_id"]
    metadata = client.get(f"/api/v1/images/{image_id}").json()
    assert metadata["media_type"] == "image/jpeg"
    assert metadata["metadata_json"]["mode"] == mode
    assert client.get(f"/api/v1/images/{image_id}/content").content == original

    create_browser_display(source, display)
    create_thumbnail(source, thumbnail, max_width=160, max_height=160)
    with Image.open(display) as rendered:
        assert rendered.mode == expected_display_mode
        assert rendered.size == (60, 80)
        assert rendered.getexif().get(274) is None
    with Image.open(thumbnail) as rendered:
        assert rendered.mode == "RGB"
        assert rendered.size == (60, 80)
        assert rendered.getexif().get(274) is None
    assert source.read_bytes() == original


@pytest.mark.parametrize(
    ("timestamp_tag", "offset_tag"),
    [(36867, 36881), (36868, 36882), (306, 36880)],
)
@pytest.mark.parametrize(
    ("offset", "expected_utc"),
    [("-04:00", "2026-10-01T16:30:00"), ("+05:30", "2026-10-01T07:00:00")],
)
def test_camera_exif_offset_normalizes_capture_time_without_mutating_original(
    client: TestClient,
    timestamp_tag: int,
    offset_tag: int,
    offset: str,
    expected_utc: str,
) -> None:
    """Explicit camera-local EXIF offsets must yield correct UTC acquisition time."""
    project = create_project(client, "Camera EXIF timezone")
    exif = Image.Exif()
    exif[timestamp_tag] = "2026:10:01 12:30:00"
    exif[offset_tag] = offset
    stream = BytesIO()
    Image.new("RGB", (64, 48), (20, 90, 120)).save(
        stream, format="JPEG", exif=exif
    )
    payload = stream.getvalue()

    report = import_one(
        client, project["id"], filename="DSC_TIME.JPEG", content=payload
    )
    assert len(report["successful"]) == 1, report
    image_id = report["successful"][0]["image_id"]
    metadata = client.get(f"/api/v1/images/{image_id}").json()
    assert metadata["capture_timestamp"].startswith(expected_utc)
    assert client.get(f"/api/v1/images/{image_id}/content").content == payload


def test_invalid_camera_exif_offset_does_not_invent_utc_capture_time(
    client: TestClient,
) -> None:
    """A malformed explicit offset must not silently be interpreted as UTC."""
    project = create_project(client, "Invalid camera EXIF timezone")
    exif = Image.Exif()
    exif[36867] = "2026:10:01 12:30:00"
    exif[36881] = "not-an-offset"
    stream = BytesIO()
    Image.new("RGB", (64, 48), (20, 90, 120)).save(
        stream, format="JPEG", exif=exif
    )
    payload = stream.getvalue()

    report = import_one(
        client, project["id"], filename="DSC_INVALID_TIME.JPEG", content=payload
    )
    assert len(report["successful"]) == 1, report
    image_id = report["successful"][0]["image_id"]
    metadata = client.get(f"/api/v1/images/{image_id}").json()
    assert metadata["capture_timestamp"] is None
    assert client.get(f"/api/v1/images/{image_id}/content").content == payload
