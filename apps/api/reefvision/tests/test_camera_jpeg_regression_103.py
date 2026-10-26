"""Camera JPEG regression coverage for the consolidated 1.0.3 import path."""

from __future__ import annotations

import struct
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from threading import Barrier, Lock
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from reefvision.storage import images as image_storage
from reefvision.storage.images import _capture_timestamp, create_browser_display, create_thumbnail
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

    display = client.get(f"/api/v1/images/{image_id}/display")
    assert display.status_code == 200
    assert display.headers["content-type"].startswith("image/png")
    with Image.open(BytesIO(display.content)) as decoded:
        assert decoded.size == (64, 48)
        assert decoded.getexif().get(274) is None


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
    ("image_format", "extension", "truncated_bytes"),
    [
        ("TIFF", ".tiff", 20),
        ("BMP", ".bmp", 20),
        ("BMP", ".dib", 20),
        ("GIF", ".gif", 10),
    ],
)
def test_truncated_static_scientific_image_rejected_before_import_commit(
    client: TestClient,
    image_format: str,
    extension: str,
    truncated_bytes: int,
) -> None:
    """Pillow verify() alone can accept a file with missing image pixels."""
    project = create_project(client, f"Truncated {image_format}")
    stream = BytesIO()
    Image.new("RGB", (120, 100), (20, 90, 120)).save(stream, format=image_format)
    truncated = stream.getvalue()[:-truncated_bytes]

    report = import_one(
        client, project["id"], filename=f"CAMERA_0002{extension}", content=truncated
    )
    assert not report["successful"], report
    assert len(report["failed"]) == 1, report


def test_multi_page_tiff_is_not_silently_imported_as_one_image(client: TestClient) -> None:
    """A scientific image stack must not be mistaken for a single 2D exposure."""
    project = create_project(client, "Multi-page TIFF")
    stream = BytesIO()
    first = Image.new("RGB", (40, 30), (20, 90, 120))
    second = Image.new("RGB", (40, 30), (120, 90, 20))
    first.save(stream, format="TIFF", save_all=True, append_images=[second])

    report = import_one(
        client, project["id"], filename="CAMERA_STACK.TIFF", content=stream.getvalue()
    )
    assert not report["successful"], report
    assert not report["failed"], report
    assert len(report["unsupported"]) == 1, report
    assert report["unsupported"][0]["status"] == "unsupported"
    assert "Multi-page TIFF" in report["unsupported"][0]["detail"]


@pytest.mark.parametrize(
    ("format_name", "extension"),
    [("PNG", ".png"), ("WEBP", ".webp")],
)
def test_animated_still_image_formats_are_rejected_without_losing_frames(
    client: TestClient, format_name: str, extension: str
) -> None:
    """APNG and animated WebP must not silently become one-frame observations."""
    project = create_project(client, f"Animated {format_name} scientific image")
    stream = BytesIO()
    first = Image.new("RGB", (40, 30), (240, 20, 20))
    second = Image.new("RGB", (40, 30), (20, 20, 240))
    first.save(
        stream,
        format=format_name,
        save_all=True,
        append_images=[second],
        duration=100,
        loop=0,
    )
    payload = stream.getvalue()
    with Image.open(BytesIO(payload)) as decoded:
        assert decoded.n_frames == 2  # A real animated fixture, not a still.

    report = import_one(
        client,
        project["id"],
        filename=f"TIME_SERIES{extension.upper()}",
        content=payload,
    )
    assert not report["successful"], report
    assert not report["failed"], report
    assert len(report["unsupported"]) == 1, report
    assert "Multi-frame" in report["unsupported"][0]["detail"]
    gallery = client.get(f"/api/v1/projects/{project['id']}/images")
    assert gallery.status_code == 200
    assert gallery.json()["total"] == 0


@pytest.mark.parametrize(
    ("orientation", "expected"),
    [
        (1, (64, 48)),
        (2, (64, 48)),
        (3, (64, 48)),
        (4, (64, 48)),
        (5, (64, 48)),
        (6, (64, 48)),
        (7, (64, 48)),
        (8, (64, 48)),
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


@pytest.mark.parametrize("orientation", range(1, 9))
def test_camera_exif_orientation_keeps_display_and_thumbnail_pixels_aligned(
    tmp_path: Path, orientation: int
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

    # The scientific coordinate frame is the original, unrotated camera raster.
    expected_size = (80, 60)
    sample_points = [(0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75)]
    for rendition in (display, thumbnail):
        with Image.open(rendition) as rendered:
            assert rendered.size == expected_size
            assert rendered.getexif().get(274) is None
            for (fx, fy), color_index in zip(sample_points, (0, 1, 2, 3), strict=True):
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
def test_non_rgb_camera_jpeg_source_aligned_display_and_oriented_thumbnail(
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
        assert rendered.size == (80, 60)
        assert rendered.getexif().get(274) is None
    with Image.open(thumbnail) as rendered:
        assert rendered.mode == "RGB"
        assert rendered.size == (80, 60)
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
    Image.new("RGB", (64, 48), (20, 90, 120)).save(stream, format="JPEG", exif=exif)
    payload = stream.getvalue()

    report = import_one(client, project["id"], filename="DSC_TIME.JPEG", content=payload)
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
    Image.new("RGB", (64, 48), (20, 90, 120)).save(stream, format="JPEG", exif=exif)
    payload = stream.getvalue()

    report = import_one(client, project["id"], filename="DSC_INVALID_TIME.JPEG", content=payload)
    assert len(report["successful"]) == 1, report
    image_id = report["successful"][0]["image_id"]
    metadata = client.get(f"/api/v1/images/{image_id}").json()
    assert metadata["capture_timestamp"] is None
    assert client.get(f"/api/v1/images/{image_id}/content").content == payload


@pytest.mark.parametrize(
    ("offset", "expected_utc"),
    [("-04:00", "2026-10-01T16:30:00"), ("+05:30", "2026-10-01T07:00:00")],
)
def test_real_camera_nested_exif_ifd_capture_time_and_provenance(
    client: TestClient, offset: str, expected_utc: str
) -> None:
    """Real camera DateTimeOriginal lives in ExifIFD, not the top-level tags."""
    project = create_project(client, "Camera nested EXIF IFD")
    exif = Image.Exif()
    # The top-level timestamp must not override the acquisition timestamp.
    exif[306] = "2026:09:30 08:00:00"
    exif[34665] = {36867: "2026:10:01 12:30:00", 36881: offset}
    stream = BytesIO()
    Image.new("RGB", (64, 48), (20, 90, 120)).save(stream, format="JPEG", exif=exif)
    payload = stream.getvalue()

    report = import_one(client, project["id"], filename="DSC_SUBIFD.JPEG", content=payload)
    assert len(report["successful"]) == 1, report
    image_id = report["successful"][0]["image_id"]
    metadata = client.get(f"/api/v1/images/{image_id}").json()
    assert metadata["capture_timestamp"].startswith(expected_utc)
    exif_metadata = metadata["metadata_json"]["exif"]
    assert exif_metadata["DateTimeOriginal"] == "2026:10:01 12:30:00"
    assert exif_metadata["OffsetTimeOriginal"] == offset
    assert client.get(f"/api/v1/images/{image_id}/content").content == payload


@pytest.mark.parametrize(
    ("timestamp_tag", "offset_tag", "subsec_tag", "subsec_name"),
    [
        (36867, 36881, 37521, "SubsecTimeOriginal"),
        (36868, 36882, 37522, "SubsecTimeDigitized"),
        (306, 36880, 37520, "SubsecTime"),
    ],
)
@pytest.mark.parametrize(
    ("subseconds", "expected_fraction"),
    [
        ("123", ".123000"),
        ("000045", ".000045"),
        ("123456789", ".123456"),
        ("not-a-fraction", ""),
    ],
)
def test_camera_exif_subseconds_preserve_acquisition_precision_and_original(
    client: TestClient,
    timestamp_tag: int,
    offset_tag: int,
    subsec_tag: int,
    subsec_name: str,
    subseconds: str,
    expected_fraction: str,
) -> None:
    """Subsecond EXIF timestamps must not be lost or borrowed across camera fields."""
    project = create_project(client, "Camera EXIF subsecond precision")
    exif = Image.Exif()
    tags = {
        timestamp_tag: "2026:10:01 12:30:00",
        offset_tag: "-04:00",
        subsec_tag: subseconds,
    }
    if timestamp_tag == 306:
        exif.update(tags)
    else:
        exif[34665] = tags
    stream = BytesIO()
    Image.new("RGB", (64, 48), (20, 90, 120)).save(stream, format="JPEG", exif=exif)
    payload = stream.getvalue()

    report = import_one(client, project["id"], filename="DSC_SUBSECOND.JPEG", content=payload)
    assert len(report["successful"]) == 1, report
    image_id = report["successful"][0]["image_id"]
    metadata = client.get(f"/api/v1/images/{image_id}").json()
    assert metadata["capture_timestamp"].startswith(f"2026-10-01T16:30:00{expected_fraction}")
    assert metadata["capture_timestamp"].endswith(("Z", "+00:00"))
    assert metadata["metadata_json"]["exif"][subsec_name] == subseconds
    assert client.get(f"/api/v1/images/{image_id}/content").content == payload


@pytest.mark.parametrize(
    ("primary_timestamp", "primary_offset"),
    [
        ("not-a-date", "-04:00"),
        ("2026:10:01 12:30:00", "invalid-offset"),
        (b"\xff", "-04:00"),
        ("2026:10:01 12:30:00", b"\xff"),
    ],
)
def test_malformed_exposure_exif_does_not_fall_back_to_digitization_or_file_time(
    primary_timestamp: str | bytes, primary_offset: str | bytes
) -> None:
    """A later digitization/file timestamp is not a valid exposure-time substitute."""
    exif = {
        36867: primary_timestamp,
        36881: primary_offset,
        36868: "2026:10:02 13:00:00",
        36882: "+00:00",
        306: "2026:10:03 14:00:00",
    }
    assert _capture_timestamp(exif) is None


def test_camera_exif_ascii_byte_strings_keep_explicit_offset_and_subseconds() -> None:
    """Preserve acquisition time when camera decoders expose EXIF ASCII as bytes."""
    exif = {
        36867: b"2026:10:01 12:30:00\x00",
        36881: b"-04:00\x00",
        37521: b"123",
    }
    assert _capture_timestamp(exif) == datetime(2026, 10, 1, 16, 30, 0, 123000, tzinfo=UTC)


def test_malformed_camera_exposure_does_not_become_digitized_time_in_api(
    client: TestClient,
) -> None:
    """Persist the image without mislabeling a later processing time as capture time."""
    project = create_project(client, "Malformed camera exposure time")
    exif = Image.Exif()
    exif[306] = "2026:10:03 14:00:00"
    exif[34665] = {
        36867: "2026:10:01 12:30:00",
        36881: "invalid-offset",
        36868: "2026:10:02 13:00:00",
        36882: "+00:00",
    }
    stream = BytesIO()
    Image.new("RGB", (64, 48), (20, 90, 120)).save(stream, format="JPEG", exif=exif)
    payload = stream.getvalue()
    report = import_one(client, project["id"], filename="DSC_BAD_OFFSET.JPEG", content=payload)
    assert len(report["successful"]) == 1, report
    image_id = report["successful"][0]["image_id"]
    metadata = client.get(f"/api/v1/images/{image_id}").json()
    assert metadata["capture_timestamp"] is None
    assert metadata["metadata_json"]["exif"]["DateTimeDigitized"] == "2026:10:02 13:00:00"
    assert client.get(f"/api/v1/images/{image_id}/content").content == payload


@pytest.mark.parametrize("rendition", ["display", "thumbnail"])
def test_parallel_camera_renditions_use_unique_temporary_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rendition: str
) -> None:
    """Concurrent thumbnail/display jobs must never delete or reuse another job's .part."""
    source = tmp_path / "CAMERA.JPEG"
    destination = tmp_path / ("display.png" if rendition == "display" else "thumb.jpg")
    Image.new("RGB", (64, 48), (20, 90, 120)).save(source, format="JPEG")
    original_bytes = source.read_bytes()
    original_save = Image.Image.save
    barrier = Barrier(2)
    lock = Lock()
    temporary_paths: list[Path] = []

    def synchronized_save(image: Image.Image, fp: str | Path, *args: Any, **kwargs: Any) -> None:
        with lock:
            temporary_paths.append(Path(fp))
        # Both workers must have chosen their temporary file before either
        # writes or atomically replaces the final destination.
        barrier.wait(timeout=20)
        original_save(image, fp, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "save", synchronized_save)

    def render() -> None:
        if rendition == "display":
            create_browser_display(source, destination)
        else:
            create_thumbnail(source, destination, max_width=128, max_height=128)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [executor.submit(render) for _ in range(2)]
        for result in results:
            result.result(timeout=30)

    assert len(temporary_paths) == 2
    assert temporary_paths[0] != temporary_paths[1]
    assert all(path.parent == tmp_path and not path.exists() for path in temporary_paths)
    with Image.open(destination) as rendered:
        rendered.load()
        assert rendered.size == (64, 48)
    assert source.read_bytes() == original_bytes


@pytest.mark.parametrize("rendition", ["display", "thumbnail"])
def test_camera_rendition_retries_transient_windows_replace_denial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rendition: str
) -> None:
    """A brief Windows destination lock must not fail an otherwise valid rendition."""
    source = tmp_path / "CAMERA.JPEG"
    destination = tmp_path / ("display.png" if rendition == "display" else "thumb.jpg")
    Image.new("RGB", (64, 48), (20, 90, 120)).save(source, format="JPEG")
    original_replace = image_storage.os.replace
    attempts = 0

    def transient_denial(source_path: Path, destination_path: Path) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("transient destination lock")
        original_replace(source_path, destination_path)

    monkeypatch.setattr(image_storage.os, "replace", transient_denial)

    if rendition == "display":
        create_browser_display(source, destination)
    else:
        create_thumbnail(source, destination, max_width=128, max_height=128)

    assert attempts == 2
    assert destination.exists()

@pytest.mark.parametrize("mode,byte_order", [("I;16L", "<"), ("I;16B", ">")])
def test_16bit_tiff_display_preserves_raw_intensity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    byte_order: str,
) -> None:
    """Browser PNGs must preserve 16-bit grayscale pixels in the raw image frame."""
    values = (0, 1, 255, 256, 30000, 65535)
    source = tmp_path / "camera-depth.tif"
    destination = tmp_path / "display.png"
    # TIFF decoders can expose either endian-specific mode. Pillow may
    # canonicalize a reopened little-endian TIFF to I;16, so explicitly mock
    # the decoder's I;16L result to exercise that branch.
    decoded = Image.frombytes(mode, (3, 2), struct.pack(f"{byte_order}6H", *values))
    decoded.save(source, format="TIFF")
    original_bytes = source.read_bytes()
    original_open = Image.open

    def open_source(path: Path | str, *args: Any, **kwargs: Any) -> Image.Image:
        if Path(path) == source:
            return decoded.copy()
        return original_open(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(image_storage.Image, "open", open_source)
        create_browser_display(source, destination)

    with Image.open(destination) as rendered:
        assert rendered.mode in {"I;16", "I;16B"}
        assert rendered.size == (3, 2)
        actual_values = tuple(
            rendered.getpixel((x, y)) for y in range(2) for x in range(3)
        )
        assert actual_values == values
    assert source.read_bytes() == original_bytes
