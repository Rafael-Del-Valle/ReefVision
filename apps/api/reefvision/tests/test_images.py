from __future__ import annotations

from io import BytesIO
from pathlib import Path
from time import monotonic, sleep
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from reefvision.config import Settings
from reefvision.db.base import Base
from reefvision.db.models import Job
from reefvision.jobs.worker import process_thumbnail_job, recover_interrupted_jobs
from reefvision.main import create_app


def image_bytes(format_name: str = "PNG", size: tuple[int, int] = (80, 60)) -> bytes:
    stream = BytesIO()
    Image.new("RGB", size, (20, 90, 120)).save(stream, format=format_name)
    return stream.getvalue()


def create_project(client: TestClient, name: str = "Gallery project") -> dict[str, Any]:
    response = client.post("/api/v1/projects", json={"name": name, "template": "octocoral"})
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


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
        "sample.png": ("PNG", "image/png"),
        "sample.tiff": ("TIFF", "image/tiff"),
        "sample.webp": ("WEBP", "image/webp"),
    }
    for index, (filename, (format_name, media_type)) in enumerate(expected.items()):
        stream = BytesIO()
        Image.new("RGB", (30 + index, 20), (index * 20, 80, 120)).save(stream, format=format_name)
        report = import_one(
            client,
            project["id"],
            filename=filename,
            content=stream.getvalue(),
            relative_path=f"formats/{filename}",
        )
        image_id = report["successful"][0]["image_id"]
        assert client.get(f"/api/v1/images/{image_id}").json()["media_type"] == media_type


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
