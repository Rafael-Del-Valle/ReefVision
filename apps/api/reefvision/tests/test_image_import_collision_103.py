"""Prevent failed imports from deleting an existing scientific image original."""

from __future__ import annotations

import errno
from pathlib import Path
from typing import BinaryIO
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import ImageAsset, Job
from reefvision.domain.errors import ValidationError
from reefvision.services import images as image_services
from reefvision.storage import images as image_storage
from reefvision.tests.test_images import create_project, image_bytes, import_one


def test_import_destination_collision_preserves_existing_original(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Immutable camera original collision")
    image_id = UUID("00000000-0000-4000-8000-000000000103")
    staging_id = UUID("00000000-0000-4000-8000-000000000104")
    original = (
        Path(test_settings.resolved_data_dir)
        / project["storage_root"]
        / "images"
        / "originals"
        / f"{image_id}.png"
    )
    original.parent.mkdir(parents=True, exist_ok=True)
    sentinel = b"previously persisted scientific image - never delete"
    original.write_bytes(sentinel)

    generated_ids = iter((staging_id, image_id))
    monkeypatch.setattr(image_services, "uuid4", lambda: next(generated_ids))

    report = import_one(
        client,
        project["id"],
        filename="new-camera-exposure.PNG",
        content=image_bytes(size=(41, 31)),
    )

    assert not report["successful"]
    assert len(report["failed"]) == 1
    assert "already exists" in report["failed"][0]["detail"]
    assert original.read_bytes() == sentinel
    assert client.get(f"/api/v1/projects/{project['id']}/images").json()["total"] == 0
    staged_path = original.parent.parent.parent / ".imports" / f"{staging_id}.part"
    assert not staged_path.exists()


def test_staging_name_collision_preserves_existing_partial_import(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Immutable staged camera upload collision")
    staging_id = UUID("00000000-0000-4000-8000-000000000105")
    staging = (
        Path(test_settings.resolved_data_dir)
        / project["storage_root"]
        / ".imports"
        / f"{staging_id}.part"
    )
    staging.parent.mkdir(parents=True, exist_ok=True)
    sentinel = b"an existing staged upload must survive a UUID collision"
    staging.write_bytes(sentinel)
    monkeypatch.setattr(image_services, "uuid4", lambda: staging_id)

    report = import_one(
        client,
        project["id"],
        filename="second-camera-exposure.PNG",
        content=image_bytes(size=(42, 31)),
    )

    assert not report["successful"]
    assert len(report["failed"]) == 1
    assert staging.read_bytes() == sentinel
    assert client.get(f"/api/v1/projects/{project['id']}/images").json()["total"] == 0


@pytest.mark.parametrize(
    ("phase", "original_error"),
    [
        ("staging", "camera card read was interrupted"),
        ("publication", "camera volume disconnected"),
    ],
)
def test_locked_partial_does_not_replace_camera_io_error_or_abort_batch(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
    original_error: str,
) -> None:
    project = create_project(client, "Read interrupted with a locked staged original")
    damaged = image_bytes(size=(41, 30))
    valid = image_bytes(size=(44, 31))
    real_stream = image_storage.stream_to_staging
    real_copy = image_storage.shutil.copyfileobj
    real_unlink = Path.unlink
    failed_partial: Path | None = None

    class InterruptedUpload:
        def __init__(self, source: BinaryIO) -> None:
            self.source = source
            self.read_started = False

        def read(self, size: int) -> bytes:
            if self.read_started:
                raise OSError(errno.EIO, original_error)
            self.read_started = True
            return self.source.read(size)

    def stream(source: BinaryIO, destination: Path) -> tuple[str, int]:
        nonlocal failed_partial
        if failed_partial is None:
            failed_partial = destination
            return real_stream(InterruptedUpload(source), destination)
        return real_stream(source, destination)

    def unsupported_link(source: Path, destination: Path) -> None:
        raise OSError(errno.EOPNOTSUPP, "volume does not support hard links")

    def copy(source: BinaryIO, destination: BinaryIO, *, length: int) -> None:
        nonlocal failed_partial
        if failed_partial is None:
            failed_partial = Path(destination.name)
            destination.write(source.read(16))
            raise OSError(errno.EIO, original_error)
        real_copy(source, destination, length=length)

    def locked_unlink(path: Path, *args: object, **kwargs: object) -> None:
        if path == failed_partial:
            raise PermissionError(errno.EACCES, "scanner holds the temporary file")
        real_unlink(path, *args, **kwargs)

    if phase == "staging":
        monkeypatch.setattr(image_services, "stream_to_staging", stream)
    else:
        monkeypatch.setattr(image_storage.os, "link", unsupported_link)
        monkeypatch.setattr(image_storage.shutil, "copyfileobj", copy)
    monkeypatch.setattr(Path, "unlink", locked_unlink)

    response = client.post(
        f"/api/v1/projects/{project['id']}/imports/images",
        files=[("files", ("interrupted.png", damaged)), ("files", ("healthy.png", valid))],
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert [row["filename"] for row in result["failed"]] == ["interrupted.png"]
    assert original_error in result["failed"][0]["detail"]
    assert [row["filename"] for row in result["successful"]] == ["healthy.png"]
    healthy_id = result["successful"][0]["image_id"]
    assert client.get(f"/api/v1/images/{healthy_id}/content").content == valid
    assert failed_partial is not None
    assert failed_partial.is_relative_to(test_settings.resolved_data_dir)
    before = failed_partial.read_bytes()

    retry = import_one(client, project["id"], filename="interrupted.png", content=damaged)
    assert len(retry["successful"]) == 1
    assert failed_partial.read_bytes() == before
    retry_id = retry["successful"][0]["image_id"]
    assert client.get(f"/api/v1/images/{retry_id}/content").content == damaged
    assert client.get(f"/api/v1/projects/{project['id']}/images").json()["total"] == 2


@pytest.mark.parametrize("damage", ["same-size", "truncated"])
def test_silent_publication_damage_is_never_registered(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    damage: str,
) -> None:
    project = create_project(client, "Do not register changed original bytes")
    original = image_bytes(size=(72, 46))
    later = image_bytes(size=(52, 33))
    original_copy = image_storage.shutil.copyfileobj
    corrupted: Path | None = None

    def unsupported_link(source: Path, destination: Path) -> None:
        raise OSError(errno.EOPNOTSUPP, "volume does not support hard links")

    def faulty_copy(source: BinaryIO, destination: BinaryIO, *, length: int) -> None:
        nonlocal corrupted
        if corrupted is not None:
            original_copy(source, destination, length=length)
            return
        corrupted = Path(destination.name)
        assert source.read() == original
        changed = (
            bytes([original[0] ^ 1]) + original[1:] if damage == "same-size" else original[:16]
        )
        destination.write(changed)

    monkeypatch.setattr(image_storage.os, "link", unsupported_link)
    monkeypatch.setattr(image_storage.shutil, "copyfileobj", faulty_copy)
    response = client.post(
        f"/api/v1/projects/{project['id']}/imports/images",
        files=[("files", ("damaged.png", original)), ("files", ("healthy.png", later))],
    )
    assert response.status_code == 200, response.text
    report = response.json()
    assert [entry["filename"] for entry in report["successful"]] == ["healthy.png"]
    assert "checksum or size changed" in report["failed"][0]["detail"]
    assert corrupted is not None and not corrupted.exists()
    assert corrupted.is_relative_to(test_settings.resolved_data_dir)
    healthy_id = report["successful"][0]["image_id"]
    assert client.get(f"/api/v1/images/{healthy_id}/content").content == later
    assert client.get(f"/api/v1/projects/{project['id']}/images").json()["total"] == 1


@pytest.mark.parametrize("damage", ["same-size", "missing", "oversized"])
def test_duplicate_import_requires_matching_managed_original(
    client: TestClient,
    test_settings: Settings,
    damage: str,
) -> None:
    project = create_project(client, "Read-only managed original verification")
    original = image_bytes(size=(73, 44))
    name = "same-original.png"
    imported = import_one(client, project["id"], filename=name, content=original)["successful"][0]
    image_id = imported["image_id"]
    row = client.get(f"/api/v1/images/{image_id}").json()
    path = test_settings.resolved_data_dir / row["managed_path"]
    assert path.read_bytes() == original
    assert (
        import_one(client, project["id"], filename=name, content=original)["duplicates"][0][
            "duplicate_image_id"
        ]
        == image_id
    )

    expected = None
    if damage == "missing":
        path.unlink()
    else:
        expected = (
            bytes([original[0] ^ 1]) + original[1:]
            if damage == "same-size"
            else original + b"extra bytes"
        )
        path.write_bytes(expected)

    failed = import_one(client, project["id"], filename=name, content=original)
    assert not failed["duplicates"]
    assert not failed["successful"]
    assert "missing, unreadable, or changed" in failed["failed"][0]["detail"]
    assert (path.read_bytes() if path.exists() else None) == expected
    assert client.get(f"/api/v1/images/{image_id}").json() == row
    assert client.get(f"/api/v1/projects/{project['id']}/images").json()["total"] == 1


def test_success_report_uses_committed_ids_without_refresh(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = create_project(client, "Durable image and thumbnail job identity")
    original = image_bytes(size=(71, 44))
    real_refresh = Session.refresh

    def failed_post_commit_refresh(
        self: Session, instance: object, *args: object, **kwargs: object
    ) -> None:
        if isinstance(instance, (ImageAsset, Job)):
            raise OSError(errno.EIO, "temporary database read interruption")
        real_refresh(self, instance, *args, **kwargs)

    monkeypatch.setattr(Session, "refresh", failed_post_commit_refresh)
    report = import_one(client, project["id"], filename="durable.png", content=original)
    listing = client.get(f"/api/v1/projects/{project['id']}/images").json()
    assert listing["total"] == 1
    assert not report["failed"], report
    item = report["successful"][0]
    assert item["image_id"] == listing["items"][0]["id"]
    job = client.get(f"/api/v1/jobs/{item['thumbnail_job_id']}").json()
    assert job["project_id"] == project["id"]
    assert job["request_json"]["image_id"] == item["image_id"]
    assert client.get(f"/api/v1/images/{item['image_id']}/content").content == original


def test_concurrent_original_placement_never_overwrites_an_existing_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another writer winning after the old exists() check must be protected."""
    staged = tmp_path / "staging.part"
    destination = tmp_path / "original.png"
    staged.write_bytes(b"new camera pixels")
    sentinel = b"already persisted scientific original"
    original_link = image_storage.os.link

    def competing_writer(source: Path, target: Path) -> None:
        destination.write_bytes(sentinel)
        original_link(source, target)

    monkeypatch.setattr(image_storage.os, "link", competing_writer)
    with pytest.raises(ValidationError, match="already exists"):
        image_storage.commit_staged_image(staged, destination)

    assert destination.read_bytes() == sentinel
    assert staged.read_bytes() == b"new camera pixels"


def test_camera_original_placement_supports_filesystems_without_hardlinks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Removable FAT/exFAT storage must remain usable without an unsafe rename."""
    staged = tmp_path / "staging.part"
    destination = tmp_path / "original.jpeg"
    original = b"camera original bytes, not a rendered preview"
    staged.write_bytes(original)

    def unsupported_hardlink(_source: Path, _target: Path) -> None:
        raise OSError(errno.EOPNOTSUPP, "Hard links are unsupported")

    monkeypatch.setattr(image_storage.os, "link", unsupported_hardlink)
    image_storage.commit_staged_image(staged, destination)

    assert destination.read_bytes() == original
    assert not staged.exists()


def test_interrupted_fallback_copy_does_not_publish_partial_camera_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An interrupted exFAT copy must retain staging and remove partial output."""
    staged = tmp_path / "staging.part"
    destination = tmp_path / "original.jpeg"
    original = b"immutable scientific camera pixels"
    staged.write_bytes(original)

    def unsupported_hardlink(_source: Path, _target: Path) -> None:
        raise OSError(errno.EOPNOTSUPP, "Hard links are unsupported")

    def interrupted_copy(_source: BinaryIO, output: BinaryIO, *, length: int) -> None:
        assert length == 1024 * 1024
        output.write(b"incomplete")
        raise OSError(errno.EIO, "Removable drive disconnected mid-copy")

    monkeypatch.setattr(image_storage.os, "link", unsupported_hardlink)
    monkeypatch.setattr(image_storage.shutil, "copyfileobj", interrupted_copy)

    with pytest.raises(OSError, match="disconnected mid-copy"):
        image_storage.commit_staged_image(staged, destination)

    assert not destination.exists()
    assert staged.read_bytes() == original


def test_fallback_original_placement_rejects_existing_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even the removable-volume fallback must never truncate an original."""
    staged = tmp_path / "staging.part"
    destination = tmp_path / "original.jpeg"
    staged.write_bytes(b"new")
    destination.write_bytes(b"original")

    def unsupported_hardlink(_source: Path, _target: Path) -> None:
        raise OSError(errno.EOPNOTSUPP, "Hard links are unsupported")

    monkeypatch.setattr(image_storage.os, "link", unsupported_hardlink)
    with pytest.raises(ValidationError, match="already exists"):
        image_storage.commit_staged_image(staged, destination)

    assert destination.read_bytes() == b"original"
    assert staged.read_bytes() == b"new"


@pytest.mark.parametrize("force_copy_fallback", [False, True])
def test_published_camera_original_survives_staging_cleanup_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, force_copy_fallback: bool
) -> None:
    """A failed staging unlink must not orphan an already-published original."""
    staged = tmp_path / "staging.part"
    destination = tmp_path / "original.jpeg"
    original = b"immutable camera exposure"
    staged.write_bytes(original)

    if force_copy_fallback:

        def unsupported_hardlink(_source: Path, _target: Path) -> None:
            raise OSError(errno.EOPNOTSUPP, "Hard links are unsupported")

        monkeypatch.setattr(image_storage.os, "link", unsupported_hardlink)

    real_unlink = Path.unlink

    def denied_staging_unlink(path: Path, *args: object, **kwargs: object) -> None:
        if path == staged:
            raise PermissionError("staging cleanup temporarily denied")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", denied_staging_unlink)
    image_storage.commit_staged_image(staged, destination)

    assert destination.read_bytes() == original
    assert staged.read_bytes() == original


def test_import_remains_recorded_when_staging_cleanup_is_denied(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An original placed on disk must not be reported as a failed import."""
    project = create_project(client, "Staging cleanup failure")
    original = image_bytes(size=(41, 31))
    real_unlink = Path.unlink

    def denied_staging_unlink(path: Path, *args: object, **kwargs: object) -> None:
        if ".imports" in path.parts and path.suffix == ".part":
            raise PermissionError("staging cleanup temporarily denied")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", denied_staging_unlink)
    report = import_one(client, project["id"], filename="CAMERA_0103.PNG", content=original)

    assert len(report["successful"]) == 1, report
    assert not report["failed"], report
    image_id = report["successful"][0]["image_id"]
    assert client.get(f"/api/v1/images/{image_id}/content").content == original
    assert client.get(f"/api/v1/projects/{project['id']}/images").json()["total"] == 1


def test_cleanup_failure_on_corrupt_image_does_not_abort_later_batch_item(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A locked invalid staging file must not hide later successful imports."""
    project = create_project(client, "Per-file staging cleanup isolation")
    valid = image_bytes(size=(43, 33))
    real_unlink = Path.unlink

    def denied_staging_unlink(path: Path, *args: object, **kwargs: object) -> None:
        if ".imports" in path.parts and path.suffix == ".part":
            raise PermissionError("staging cleanup temporarily denied")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", denied_staging_unlink)
    response = client.post(
        f"/api/v1/projects/{project['id']}/imports/images",
        files=[
            ("files", ("broken.png", b"not an image", "image/png")),
            ("files", ("valid.png", valid, "image/png")),
        ],
        data={"relative_paths": ["camera/broken.png", "camera/valid.png"]},
    )

    assert response.status_code == 200, response.text
    report = response.json()
    assert [item["filename"] for item in report["failed"]] == ["broken.png"]
    assert [item["filename"] for item in report["successful"]] == ["valid.png"]
    image_id = report["successful"][0]["image_id"]
    assert client.get(f"/api/v1/images/{image_id}/content").content == valid


@pytest.mark.parametrize("subseconds", [b"123400\x00", "123400\x00"])
def test_camera_exif_nul_terminated_subseconds_are_preserved(
    subseconds: bytes | str,
) -> None:
    """Camera EXIF ASCII fields may include a terminating NUL byte."""
    timestamp = image_storage._capture_timestamp({36867: "2026:10:25 10:11:12", 37521: subseconds})

    assert timestamp is not None
    assert timestamp.microsecond == 123400
    assert timestamp.isoformat() == "2026-10-25T10:11:12.123400+00:00"


@pytest.mark.parametrize("as_bytes", [False, True])
def test_camera_exif_nul_terminated_timestamp_and_offset(as_bytes: bool) -> None:
    """NUL-padded camera ASCII fields must retain their UTC offset."""
    raw: str | bytes = "2026:10:25 10:11:12\x00"
    offset: str | bytes = "-04:00\x00"
    if as_bytes:
        raw = b"2026:10:25 10:11:12\x00"
        offset = b"-04:00\x00"
    timestamp = image_storage._capture_timestamp({36867: raw, 36881: offset, 37521: "123456\x00"})
    assert timestamp is not None
    assert timestamp.isoformat() == "2026-10-25T14:11:12.123456+00:00"
