from __future__ import annotations

from io import BytesIO
from pathlib import Path
from time import monotonic, sleep
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import ExifTags, Image

from reefvision.config import Settings
from reefvision.db.base import Base
from reefvision.db.models import Job, MaskAnnotation
from reefvision.jobs.worker import process_thumbnail_job, recover_interrupted_jobs
from reefvision.main import create_app
from reefvision.tests.class_fixtures import seed_synthetic_label_classes


def image_bytes(format_name: str = "PNG", size: tuple[int, int] = (80, 60)) -> bytes:
    stream = BytesIO()
    Image.new("RGB", size, (20, 90, 120)).save(stream, format=format_name)
    return stream.getvalue()


def create_project(
    client: TestClient,
    name: str = "Gallery project",
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/projects",
        json={
            "name": name,
            "template": "blank",
        },
    )
    assert response.status_code == 201, response.text

    return seed_synthetic_label_classes(
        client,
        cast(dict[str, Any], response.json()),
    )


def import_one(
    client: TestClient,
    project_id: str,
    *,
    filename: str = "coral.png",
    content: bytes | None = None,
    relative_path: str = "trial-1/coral.png",
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/projects/{project_id}/imports/images",
        files=[("files", (filename, content or image_bytes(), "application/octet-stream"))],
        data={"relative_paths": relative_path},
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


def test_import_records_metadata_and_managed_copy(
    client: TestClient, test_settings: Settings
) -> None:
    project = create_project(client)
    report = import_one(client, project["id"])

    assert len(report["successful"]) == 1
    item = report["successful"][0]
    image_response = client.get(f"/api/v1/images/{item['image_id']}")
    assert image_response.status_code == 200
    image = image_response.json()
    assert image["width_px"] == 80
    assert image["height_px"] == 60
    assert image["media_type"] == "image/png"
    assert image["import_source"] == "trial-1/coral.png"
    assert image["metadata_json"]["format"] == "PNG"
    assert image["annotation_status"] == "unannotated"
    assert image["annotation_revision"] == 0
    assert (test_settings.resolved_data_dir / image["managed_path"]).is_file()

    content = client.get(f"/api/v1/images/{item['image_id']}/content")
    assert content.status_code == 200
    assert content.content == image_bytes()
    assert content.headers["content-disposition"].startswith("inline;")


def test_duplicate_corrupt_and_unsupported_files_are_reported(client: TestClient) -> None:
    project = create_project(client)
    first = import_one(client, project["id"])
    duplicate = import_one(client, project["id"], filename="renamed.png")
    corrupt = import_one(client, project["id"], filename="broken.png", content=b"not image")
    unsupported = import_one(client, project["id"], filename="notes.txt", content=b"text")

    assert len(first["successful"]) == 1
    assert duplicate["duplicates"][0]["duplicate_image_id"] == first["successful"][0]["image_id"]
    assert corrupt["failed"][0]["status"] == "failed"
    assert unsupported["unsupported"][0]["status"] == "unsupported"

    page = client.get(f"/api/v1/projects/{project['id']}/images").json()
    assert page["total"] == 1


def test_thumbnail_job_is_persisted_processed_and_retryable(
    client: TestClient, test_settings: Settings
) -> None:
    project = create_project(client)
    report = import_one(client, project["id"])
    item = report["successful"][0]
    job_id = item["thumbnail_job_id"]

    queued = client.get(f"/api/v1/jobs/{job_id}")
    assert queued.status_code == 200
    assert queued.json()["status"] == "queued"

    app = cast(FastAPI, client.app)
    factory = app.state.session_factory
    assert process_thumbnail_job(test_settings, factory, job_id)

    completed = client.get(f"/api/v1/jobs/{job_id}").json()
    assert completed["status"] == "succeeded"
    assert completed["progress_current"] == 1
    thumbnail = client.get(f"/api/v1/images/{item['image_id']}/thumbnail")
    assert thumbnail.status_code == 200
    assert thumbnail.headers["content-type"].startswith("image/jpeg")

    retry = client.post(f"/api/v1/jobs/{job_id}/retry")
    assert retry.status_code == 409


def test_missing_source_marks_thumbnail_failed_then_allows_retry(
    client: TestClient, test_settings: Settings
) -> None:
    project = create_project(client)
    report = import_one(client, project["id"])
    item = report["successful"][0]
    image = client.get(f"/api/v1/images/{item['image_id']}").json()
    (test_settings.resolved_data_dir / image["managed_path"]).unlink()

    app = cast(FastAPI, client.app)
    factory = app.state.session_factory
    assert not process_thumbnail_job(test_settings, factory, item["thumbnail_job_id"])
    failed = client.get(f"/api/v1/jobs/{item['thumbnail_job_id']}").json()
    assert failed["status"] == "failed"
    assert "missing" in failed["error_message"].lower()

    retry = client.post(f"/api/v1/jobs/{item['thumbnail_job_id']}/retry")
    assert retry.status_code == 200
    assert retry.json()["status"] == "queued"


def test_gallery_pagination_filters_and_updates_are_stable(client: TestClient) -> None:
    project = create_project(client)
    colors = [(5, 10, 15), (15, 20, 25), (25, 30, 35)]
    ids: list[str] = []
    for index, color in enumerate(colors):
        stream = BytesIO()
        Image.new("RGB", (40 + index, 30), color).save(stream, format="PNG")
        report = import_one(
            client,
            project["id"],
            filename=f"coral-{index}.png",
            content=stream.getvalue(),
            relative_path=f"whole-{index}/coral.png",
        )
        ids.append(report["successful"][0]["image_id"])

    first_update = client.patch(
        f"/api/v1/images/{ids[0]}",
        json={"group_key": "source-A", "annotation_status": "reviewed"},
    )
    assert first_update.status_code == 200

    page_one = client.get(
        f"/api/v1/projects/{project['id']}/images", params={"page": 1, "page_size": 2}
    ).json()
    page_two = client.get(
        f"/api/v1/projects/{project['id']}/images", params={"page": 2, "page_size": 2}
    ).json()
    assert page_one["total"] == 3
    assert page_one["pages"] == 2
    assert len(page_one["items"]) == 2
    assert len(page_two["items"]) == 1
    assert {item["id"] for item in page_one["items"]}.isdisjoint(
        {item["id"] for item in page_two["items"]}
    )
    assert page_one["items"][0]["id"] == ids[-1]

    filename_page_one = client.get(
        f"/api/v1/projects/{project['id']}/images",
        params={"page": 1, "page_size": 2, "sort_by": "filename"},
    ).json()
    filename_page_two = client.get(
        f"/api/v1/projects/{project['id']}/images",
        params={"page": 2, "page_size": 2, "sort_by": "filename"},
    ).json()
    assert [item["original_filename"] for item in filename_page_one["items"]] == [
        "coral-0.png",
        "coral-1.png",
    ]
    assert [item["original_filename"] for item in filename_page_two["items"]] == ["coral-2.png"]

    app = cast(FastAPI, client.app)
    factory = app.state.session_factory
    with factory() as session:
        session.add(
            MaskAnnotation(
                image_id=ids[0],
                geometry_kind="polygon",
                polygon_json=[[1.0, 1.0], [5.0, 1.0], [5.0, 5.0]],
                x_min=1.0,
                y_min=1.0,
                x_max=5.0,
                y_max=5.0,
                area_pixels=8,
                source_type="human",
                status="verified",
            )
        )
        session.commit()
    counted = client.get(f"/api/v1/images/{ids[0]}").json()
    assert counted["annotation_count"] == 1

    by_name = client.get(
        f"/api/v1/projects/{project['id']}/images", params={"filename": "coral-1"}
    ).json()
    assert by_name["total"] == 1
    by_status = client.get(
        f"/api/v1/projects/{project['id']}/images",
        params={"annotation_status": "reviewed"},
    ).json()
    assert by_status["items"][0]["id"] == ids[0]
    by_group = client.get(
        f"/api/v1/projects/{project['id']}/images", params={"group_key": "source-A"}
    ).json()
    assert by_group["total"] == 1


def test_running_jobs_are_recovered_without_losing_records(client: TestClient) -> None:
    project = create_project(client)
    report = import_one(client, project["id"])
    job_id = report["successful"][0]["thumbnail_job_id"]
    app = cast(FastAPI, client.app)
    factory = app.state.session_factory
    with factory() as session:
        job = session.get(Job, job_id)
        assert job is not None
        job.status = "running"
        session.commit()

    assert recover_interrupted_jobs(factory) == 1
    recovered = client.get(f"/api/v1/jobs/{job_id}").json()
    assert recovered["status"] == "queued"
    assert "Recovered" in recovered["error_message"]


def test_supported_image_formats_import(client: TestClient) -> None:
    project = create_project(client, "Format coverage")
    expected = {
        "sample.jpg": ("JPEG", "image/jpeg"),
        "sample.jpeg": ("JPEG", "image/jpeg"),
        "sample.JPG": ("JPEG", "image/jpeg"),
        "sample.JPEG": ("JPEG", "image/jpeg"),
        "sample.jpe": ("JPEG", "image/jpeg"),
        "sample.JPE": ("JPEG", "image/jpeg"),
        "sample.JFIF": ("JPEG", "image/jpeg"),
        "sample.jfif": ("JPEG", "image/jpeg"),
        "sample.jfi": ("JPEG", "image/jpeg"),
        "sample.JFI": ("JPEG", "image/jpeg"),
        "sample.jif": ("JPEG", "image/jpeg"),
        "sample.JIF": ("JPEG", "image/jpeg"),
        "sample.png": ("PNG", "image/png"),
        "sample.tif": ("TIFF", "image/tiff"),
        "sample.tiff": ("TIFF", "image/tiff"),
        "sample.TIFF": ("TIFF", "image/tiff"),
        "sample.webp": ("WEBP", "image/webp"),
        "sample.bmp": ("BMP", "image/bmp"),
        "sample.DIB": ("BMP", "image/bmp"),
        "sample.gif": ("GIF", "image/gif"),
    }
    for index, (filename, (format_name, media_type)) in enumerate(expected.items()):
        stream = BytesIO()
        Image.new("RGB", (30 + index, 20), ((index * 17) % 256, 80, 120)).save(
            stream, format=format_name
        )
        original_bytes = stream.getvalue()
        report = import_one(
            client,
            project["id"],
            filename=filename,
            content=original_bytes,
            relative_path=f"formats/{filename}",
        )
        image_id = report["successful"][0]["image_id"]
        record = client.get(f"/api/v1/images/{image_id}").json()
        assert record["media_type"] == media_type
        assert (record["width_px"], record["height_px"]) == (30 + index, 20)
        assert record["original_filename"] == filename
        assert client.get(f"/api/v1/images/{image_id}/content").content == original_bytes


def test_malformed_camera_exif_does_not_discard_decodable_jpeg(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A corrupt acquisition IFD must not erase valid pixels or invent a timestamp."""
    project = create_project(client, "Camera JPEG with damaged EXIF")
    camera_exif = Image.Exif()
    camera_exif[274] = 6
    # A top-level DateTime is not proof of exposure time if the nested
    # DateTimeOriginal/OffsetTimeOriginal IFD is unreadable.
    camera_exif[306] = "2026:10:25 14:15:16"
    stream = BytesIO()
    Image.new("RGB", (64, 48), (20, 90, 120)).save(
        stream, format="JPEG", exif=camera_exif
    )
    original = stream.getvalue()

    original_get_ifd = Image.Exif.get_ifd

    def broken_nested_ifd(self: Image.Exif, ifd: int) -> dict[int, Any]:
        if ifd == ExifTags.IFD.Exif:
            raise ValueError("camera nested EXIF pointer is invalid")
        return original_get_ifd(self, ifd)

    monkeypatch.setattr(Image.Exif, "get_ifd", broken_nested_ifd)
    report = import_one(
        client, project["id"], filename="camera-corrupt-exif.JPEG", content=original
    )
    assert len(report["successful"]) == 1, report
    assert not report["failed"]
    image_id = report["successful"][0]["image_id"]
    record = client.get(f"/api/v1/images/{image_id}").json()
    assert (record["width_px"], record["height_px"]) == (64, 48)
    assert record["capture_timestamp"] is None
    assert "Nested EXIF" in record["metadata_json"]["exif_warning"]
    assert record["metadata_json"]["exif"]["Orientation"] == 6
    assert client.get(f"/api/v1/images/{image_id}/content").content == original

    display = client.get(f"/api/v1/images/{image_id}/display")
    assert display.status_code == 200
    with Image.open(BytesIO(display.content)) as rendition:
        assert rendition.size == (64, 48)
        assert rendition.getexif().get(274) in (None, 1)


@pytest.mark.parametrize("orientation", range(2, 9))
def test_exif_oriented_jpeg_display_preserves_raw_pixel_geometry(
    client: TestClient, orientation: int
) -> None:
    """WebView2 and thumbnails must preserve original camera axes for every EXIF rotation."""
    project = create_project(client, f"EXIF orientation {orientation} geometry")
    original_image = Image.new("RGB", (64, 48))
    colors = [(240, 20, 20), (20, 240, 20), (20, 20, 240), (240, 240, 20)]
    for (x, y), color in zip([(0, 0), (32, 0), (0, 24), (32, 24)], colors, strict=True):
        original_image.paste(color, (x, y, x + 32, y + 24))
    exif = Image.Exif()
    exif[274] = orientation
    stream = BytesIO()
    original_image.save(stream, format="JPEG", quality=100, subsampling=0, exif=exif)
    original = stream.getvalue()

    report = import_one(
        client,
        project["id"],
        filename="camera-orientation.JPG",
        content=original,
    )
    image_id = report["successful"][0]["image_id"]
    record = client.get(f"/api/v1/images/{image_id}").json()
    assert (record["width_px"], record["height_px"]) == (64, 48)
    assert record["metadata_json"]["exif"]["Orientation"] == orientation

    content = client.get(f"/api/v1/images/{image_id}/content")
    assert content.content == original
    for route, expected_type in (("display", "image/png"), ("thumbnail", "image/jpeg")):
        response = client.get(f"/api/v1/images/{image_id}/{route}")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith(expected_type)
        with Image.open(BytesIO(response.content)) as rendition:
            assert rendition.width * 48 == rendition.height * 64
            assert rendition.getexif().get(274) in (None, 1)
            rgb = rendition.convert("RGB")
            for (fx, fy), expected in zip(
                [(0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75)],
                colors,
                strict=True,
            ):
                actual = rgb.getpixel((int(rgb.width * fx), int(rgb.height * fy)))
                assert all(
                    abs(channel - reference) < 45
                    for channel, reference in zip(actual, expected, strict=True)
                )
    assert client.get(f"/api/v1/images/{image_id}/content").content == original


def test_cmyk_jpeg_import_has_browser_safe_display(client: TestClient) -> None:
    project = create_project(client, "CMYK JPEG")
    stream = BytesIO()
    Image.new("CMYK", (64, 48), (80, 20, 30, 10)).save(stream, format="JPEG")
    report = import_one(
        client,
        project["id"],
        filename="lab-export.JPEG",
        content=stream.getvalue(),
    )
    image_id = report["successful"][0]["image_id"]
    original = client.get(f"/api/v1/images/{image_id}/content")
    assert original.status_code == 200
    assert original.headers["content-type"].startswith("image/jpeg")
    display = client.get(f"/api/v1/images/{image_id}/display")
    assert display.status_code == 200
    assert display.headers["content-type"].startswith("image/png")
    with Image.open(BytesIO(display.content)) as decoded:
        assert decoded.size == (64, 48)


def test_animated_gif_is_rejected_instead_of_silently_losing_frames(
    client: TestClient,
) -> None:
    project = create_project(client, "Animated image validation")
    stream = BytesIO()
    Image.new("RGB", (32, 24), "red").save(
        stream,
        format="GIF",
        save_all=True,
        append_images=[Image.new("RGB", (32, 24), "blue")],
        duration=100,
        loop=0,
    )
    report = import_one(
        client,
        project["id"],
        filename="sequence.gif",
        content=stream.getvalue(),
    )
    assert len(report["successful"]) == 0
    assert len(report["unsupported"]) == 1
    assert "Animated GIFs" in report["unsupported"][0]["detail"]


def test_imports_16_bit_grayscale_tiff(client: TestClient, test_settings: Settings) -> None:
    project = create_project(client, "16-bit TIFF coverage")
    stream = BytesIO()
    Image.new("I;16", (64, 48), 2048).save(stream, format="TIFF")

    report = import_one(
        client,
        project["id"],
        filename="microscopy-16bit.tif",
        content=stream.getvalue(),
        relative_path="microscopy/microscopy-16bit.tif",
    )

    assert len(report["successful"]) == 1
    assert not report["failed"]
    item = report["successful"][0]
    image_id = item["image_id"]
    image = client.get(f"/api/v1/images/{image_id}").json()
    assert image["media_type"] == "image/tiff"
    assert image["width_px"] == 64
    assert image["height_px"] == 48
    assert image["metadata_json"]["mode"] == "I;16"

    display = client.get(f"/api/v1/images/{image_id}/display")
    assert display.status_code == 200
    assert display.headers["content-type"].startswith("image/png")
    with Image.open(BytesIO(display.content)) as display_image:
        assert display_image.size == (64, 48)
        assert display_image.mode == "I;16"

    app = cast(FastAPI, client.app)
    factory = app.state.session_factory
    assert process_thumbnail_job(test_settings, factory, item["thumbnail_job_id"])
    thumbnail = client.get(f"/api/v1/images/{image_id}/thumbnail")
    assert thumbnail.status_code == 200
    with Image.open(BytesIO(thumbnail.content)) as thumbnail_image:
        extrema = thumbnail_image.getextrema()
        assert extrema != ((255, 255), (255, 255), (255, 255))


def test_big_endian_16_bit_tiff_renditions_preserve_original_pixel_values(
    client: TestClient, test_settings: Settings
) -> None:
    """A big-endian TIFF stays 16-bit in display and yields a readable JPEG thumbnail."""
    project = create_project(client, "Big-endian TIFF camera import")
    stream = BytesIO()
    Image.new("I;16B", (64, 48), 2048).save(stream, format="TIFF")
    original = stream.getvalue()
    report = import_one(
        client,
        project["id"],
        filename="camera-big-endian.TIF",
        content=original,
    )
    assert len(report["successful"]) == 1, report
    image_id = report["successful"][0]["image_id"]
    record = client.get(f"/api/v1/images/{image_id}").json()
    assert record["metadata_json"]["mode"] == "I;16B"
    assert (record["width_px"], record["height_px"]) == (64, 48)

    response = client.get(f"/api/v1/images/{image_id}/display")
    assert response.status_code == 200
    with Image.open(BytesIO(response.content)) as display:
        assert display.mode == "I;16"
        assert display.size == (64, 48)
        assert display.getpixel((0, 0)) == 2048

    app = cast(FastAPI, client.app)
    factory = app.state.session_factory
    assert process_thumbnail_job(
        test_settings, factory, report["successful"][0]["thumbnail_job_id"]
    )
    thumbnail = client.get(f"/api/v1/images/{image_id}/thumbnail")
    assert thumbnail.status_code == 200
    with Image.open(BytesIO(thumbnail.content)) as preview:
        assert preview.mode == "RGB"
        assert all(2 <= channel <= 20 for channel in preview.getpixel((0, 0)))

    # Neither browser-safe rendition modifies the original camera bytes.
    assert client.get(f"/api/v1/images/{image_id}/content").content == original


@pytest.mark.parametrize("mode", ["I;16B", "I;16L"])
def test_endian_16_bit_tiff_preserves_source_and_raw_pixel_display(
    client: TestClient, test_settings: Settings, mode: str
) -> None:
    """Scientific TIFF import must not silently downsample 16-bit source pixels."""
    project = create_project(client, f"Endian TIFF {mode}")
    stream = BytesIO()
    Image.new(mode, (64, 48), 4096).save(stream, format="TIFF")
    original = stream.getvalue()

    report = import_one(
        client,
        project["id"],
        filename=f"depth-{mode.replace(';', '-')}.tiff",
        content=original,
    )
    assert len(report["successful"]) == 1
    assert not report["failed"]
    item = report["successful"][0]
    image_id = item["image_id"]
    assert client.get(f"/api/v1/images/{image_id}/content").content == original

    display = client.get(f"/api/v1/images/{image_id}/display")
    assert display.status_code == 200
    assert display.headers["content-type"].startswith("image/png")
    with Image.open(BytesIO(display.content)) as rendition:
        assert rendition.size == (64, 48)
        assert rendition.getpixel((32, 24)) == 4096

    app = cast(FastAPI, client.app)
    assert process_thumbnail_job(test_settings, app.state.session_factory, item["thumbnail_job_id"])
    thumbnail = client.get(f"/api/v1/images/{image_id}/thumbnail")
    assert thumbnail.status_code == 200
    with Image.open(BytesIO(thumbnail.content)) as rendition:
        assert rendition.size == (64, 48)
        pixel = rendition.convert("RGB").getpixel((32, 24))
        assert all(10 <= channel <= 20 for channel in pixel)
    assert client.get(f"/api/v1/images/{image_id}/content").content == original


def test_truncated_camera_jpeg_is_rejected_without_persisting_an_image(
    client: TestClient,
) -> None:
    """A valid JPEG header is not proof that all scientific pixels decode."""
    project = create_project(client, "Truncated camera JPEG")
    stream = BytesIO()
    Image.new("RGB", (128, 96), (20, 90, 120)).save(stream, format="JPEG")
    truncated = stream.getvalue()[:-32]
    report = import_one(client, project["id"], filename="camera-capture.JPEG", content=truncated)

    assert not report["successful"]
    assert len(report["failed"]) == 1
    assert report["failed"][0]["status"] == "failed"
    page = client.get(f"/api/v1/projects/{project['id']}/images").json()
    assert page["total"] == 0


def test_batch_imports_ten_images(client: TestClient) -> None:
    project = create_project(client, "Batch import")
    files = []
    relative_paths = []
    original_payloads: list[bytes] = []
    for index in range(10):
        stream = BytesIO()
        Image.new("RGB", (32 + index, 24), (index, 100, 150)).save(stream, format="PNG")
        payload = stream.getvalue()
        original_payloads.append(payload)
        files.append(("files", (f"coral-{index}.png", payload, "image/png")))
        relative_paths.append(f"batch/coral-{index}.png")

    response = client.post(
        f"/api/v1/projects/{project['id']}/imports/images",
        files=files,
        data={"relative_paths": relative_paths},
    )
    assert response.status_code == 200, response.text
    report = response.json()
    assert len(report["successful"]) == 10
    assert not report["failed"]
    assert all(payload.startswith(b"\x89PNG") for payload in original_payloads)
    page = client.get(f"/api/v1/projects/{project['id']}/images", params={"page_size": 100}).json()
    assert page["total"] == 10


def test_enabled_worker_generates_thumbnail_in_background(tmp_path: Path) -> None:
    settings = Settings(
        env="test",
        data_dir=tmp_path / "worker-data",
        database_url=f"sqlite:///{(tmp_path / 'worker.db').as_posix()}",
        web_origin="http://testserver",
        background_worker_enabled=True,
        worker_poll_seconds=0.01,
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as worker_client:
        project = create_project(worker_client, "Background worker")
        report = import_one(worker_client, project["id"])
        item = report["successful"][0]
        deadline = monotonic() + 3
        status = "queued"
        while monotonic() < deadline and status not in {"succeeded", "failed"}:
            sleep(0.02)
            status = worker_client.get(f"/api/v1/jobs/{item['thumbnail_job_id']}").json()["status"]
        assert status == "succeeded"
        assert worker_client.get(f"/api/v1/images/{item['image_id']}/thumbnail").status_code == 200
    Base.metadata.drop_all(app.state.engine)
    app.state.engine.dispose()
