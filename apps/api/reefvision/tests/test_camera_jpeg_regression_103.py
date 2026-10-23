"""Camera JPEG regression coverage for the consolidated 1.0.3 import path."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from reefvision.storage.images import create_browser_display
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
    Image.new("RGB", (512, 512), (20, 30, 40)).save(
        stream, format="JPEG", progressive=progressive
    )
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
