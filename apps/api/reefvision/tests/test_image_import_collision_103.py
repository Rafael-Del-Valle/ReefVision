"""Prevent failed imports from deleting an existing scientific image original."""

from __future__ import annotations

import errno
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import BinaryIO
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from reefvision.config import Settings
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


def test_interrupted_camera_upload_preserves_read_error_when_windows_locks_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An antivirus lock must not conceal the original card read failure."""
    partial = tmp_path / "locked-camera.part"
    source_bytes = b"camera card bytes before a transient read failure"

    class InterruptedCameraStream(BytesIO):
        def __init__(self) -> None:
            super().__init__(source_bytes)
            self.read_calls = 0

        def read(self, size: int = -1) -> bytes:
            self.read_calls += 1
            if self.read_calls > 1:
                raise OSError(errno.EIO, "camera card disconnected during upload")
            return super().read(size)

    original_unlink = Path.unlink

    def locked_partial_unlink(path: Path, *args: object, **kwargs: object) -> None:
        if path == partial:
            raise PermissionError("Windows scanner temporarily holds partial staging file")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked_partial_unlink)
    with pytest.raises(OSError, match="camera card disconnected during upload"):
        image_storage.stream_to_staging(InterruptedCameraStream(), partial)

    # The partial staging file is never registered as a scientific original.
    # Preserve the underlying read failure so the operator can troubleshoot.
    assert partial.read_bytes() == source_bytes
    assert "Could not remove incomplete camera import artifact" in caplog.text

    # A fresh retry uses a new exclusive staging name, never the orphan.
    retried = tmp_path / "camera-retry.part"
    digest, size = image_storage.stream_to_staging(BytesIO(source_bytes), retried)
    assert (digest, size) == (sha256(source_bytes).hexdigest(), len(source_bytes))
    assert retried.read_bytes() == source_bytes
    assert partial.read_bytes() == source_bytes


def test_removable_camera_copy_preserves_io_error_when_partial_original_is_locked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed exFAT copy must not be mistaken for a cleanup permission error."""
    staged = tmp_path / "staging.part"
    destination = tmp_path / "camera-original.jpeg"
    staged_bytes = b"staged immutable camera bytes"
    staged.write_bytes(staged_bytes)

    def unsupported_hardlink(_source: Path, _target: Path) -> None:
        raise OSError(errno.EOPNOTSUPP, "exFAT cannot create hard links")

    def disconnected_copy(_source: BinaryIO, output: BinaryIO, *, length: int) -> None:
        assert length == 1024 * 1024
        output.write(b"incomplete")
        raise OSError(errno.EIO, "camera volume disconnected mid-copy")

    original_unlink = Path.unlink

    def locked_destination_unlink(path: Path, *args: object, **kwargs: object) -> None:
        if path == destination:
            raise PermissionError("Windows scanner temporarily holds incomplete copy")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(image_storage.os, "link", unsupported_hardlink)
    monkeypatch.setattr(image_storage.shutil, "copyfileobj", disconnected_copy)
    monkeypatch.setattr(Path, "unlink", locked_destination_unlink)

    with pytest.raises(OSError, match="camera volume disconnected mid-copy"):
        image_storage.commit_staged_image(staged, destination)

    assert staged.read_bytes() == staged_bytes
    # The unreferenced partial may remain until the Windows handle is
    # released, but the failed publication must not report success.
    assert destination.read_bytes() == b"incomplete"
    assert "Could not remove incomplete camera import artifact" in caplog.text


@pytest.mark.parametrize("damage", ["same_size", "truncated"])
def test_removable_camera_import_rejects_silent_copy_corruption(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    damage: str,
) -> None:
    """A successful exFAT copy syscall is not proof of immutable camera bytes."""
    project = create_project(client, "Removable camera checksum verification")
    source = image_bytes("JPEG", size=(51, 37))

    def unsupported_hardlink(_source: Path, _target: Path) -> None:
        raise OSError(errno.EOPNOTSUPP, "Hard links are unsupported on this volume")

    def corrupted_copy(input_file: BinaryIO, output: BinaryIO, *, length: int) -> None:
        assert length == 1024 * 1024
        camera_bytes = input_file.read()
        if damage == "truncated":
            output.write(camera_bytes[:-1])
        else:
            # Keep the byte count unchanged: a length-only check would miss it.
            output.write(bytes([camera_bytes[0] ^ 1]) + camera_bytes[1:])

    monkeypatch.setattr(image_storage.os, "link", unsupported_hardlink)
    monkeypatch.setattr(image_storage.shutil, "copyfileobj", corrupted_copy)

    report = import_one(client, project["id"], filename="SONY_REMOVABLE_0103.JPEG", content=source)

    assert report["successful"] == []
    assert len(report["failed"]) == 1, report
    assert "checksum or size changed" in report["failed"][0]["detail"]
    assert client.get(f"/api/v1/projects/{project['id']}/images").json()["total"] == 0
    original_directory = (
        Path(test_settings.resolved_data_dir) / project["storage_root"] / "images" / "originals"
    )
    assert list(original_directory.iterdir()) == []


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
@pytest.mark.parametrize("offset", [None, b"+00:00\x00", "+00:00\x00"])
def test_camera_exif_nul_terminated_subseconds_respect_timezone_provenance(
    subseconds: bytes | str,
    offset: bytes | str | None,
) -> None:
    """NUL-terminated camera fractions are valid, but never imply a UTC offset."""
    exif: dict[int, object] = {36867: "2026:10:25 10:11:12", 37521: subseconds}
    if offset is not None:
        exif[36881] = offset
    timestamp = image_storage._capture_timestamp(exif)

    if offset is None:
        # A camera-local wall clock is not a scientifically verified UTC instant.
        assert timestamp is None
    else:
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


@pytest.mark.parametrize(
    ("camera_time", "offset", "expected_utc", "warning_fragment"),
    [
        ("2026:10:25 10:11:12", None, None, "no UTC offset"),
        ("2026:10:25 10:11:12", "+99:99", None, "invalid"),
        ("2026:13:25 10:11:12", "+00:00", None, "invalid"),
        ("2026:10:25 10:11:12", "+00:00", "2026-10-25T10:11:12+00:00", None),
    ],
)
def test_camera_jpeg_exif_time_qc_preserves_original_bytes(
    tmp_path: Path,
    camera_time: str,
    offset: str | None,
    expected_utc: str | None,
    warning_fragment: str | None,
) -> None:
    """Malformed camera clocks must retain source bytes and visible time uncertainty."""
    source = tmp_path / "IMG_0103.JPG"
    exif = Image.Exif()
    exif[36867] = camera_time
    if offset is not None:
        exif[36881] = offset
    Image.new("RGB", (17, 13), (20, 40, 60)).save(source, format="JPEG", exif=exif)
    original = source.read_bytes()
    digest = sha256(original).hexdigest()

    inspected = image_storage.inspect_staged_image(source, digest, len(original))

    assert inspected.sha256 == digest
    assert inspected.media_type == "image/jpeg"
    assert inspected.metadata["exif"]["DateTimeOriginal"] == camera_time
    assert source.read_bytes() == original
    if expected_utc is None:
        assert inspected.capture_timestamp is None
        assert warning_fragment in inspected.metadata["capture_time_warning"]
    else:
        assert inspected.capture_timestamp is not None
        assert inspected.capture_timestamp.isoformat() == expected_utc
        assert "capture_time_warning" not in inspected.metadata


def test_committed_camera_import_does_not_require_a_second_database_refresh(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed post-commit refresh must not reclassify a durable JPEG as failed."""
    from sqlalchemy.orm import Session

    from reefvision.db.models import ImageAsset, Job

    project = create_project(client, "Committed camera import response integrity")
    source = image_bytes("JPEG", size=(47, 31))
    original_refresh = Session.refresh

    def reject_import_refresh(
        session: Session, instance: object, *args: object, **kwargs: object
    ) -> None:
        if isinstance(instance, (ImageAsset, Job)):
            raise OSError("Simulated database read outage after image commit")
        original_refresh(session, instance, *args, **kwargs)

    monkeypatch.setattr(Session, "refresh", reject_import_refresh)
    try:
        report = import_one(client, project["id"], filename="SONY_DSC_0103.JPG", content=source)
    finally:
        monkeypatch.setattr(Session, "refresh", original_refresh)

    assert len(report["successful"]) == 1, report
    assert report["failed"] == [], report
    entry = report["successful"][0]
    assert entry["filename"] == "SONY_DSC_0103.JPG"
    assert entry["thumbnail_job_id"]
    original = client.get(f"/api/v1/images/{entry['image_id']}/content")
    assert original.status_code == 200
    assert original.content == source
    job = client.get(f"/api/v1/jobs/{entry['thumbnail_job_id']}")
    assert job.status_code == 200
    assert job.json()["status"] == "queued"
    assert client.get(f"/api/v1/projects/{project['id']}/images").json()["total"] == 1

    duplicate = import_one(client, project["id"], filename="camera-resend.JPEG", content=source)
    assert duplicate["successful"] == []
    assert duplicate["duplicates"][0]["duplicate_image_id"] == entry["image_id"]


@pytest.mark.parametrize("damage", ["missing", "truncated", "same_size_corruption"])
def test_camera_duplicate_requires_intact_managed_original(
    client: TestClient,
    test_settings: Settings,
    damage: str,
) -> None:
    """A database hash must never conceal loss of scientific source pixels."""
    project = create_project(client, "Duplicate camera source integrity")
    original_bytes = image_bytes("JPEG", size=(53, 39))
    first = import_one(
        client,
        project["id"],
        filename="SONY_DSC_2026.JPG",
        content=original_bytes,
    )
    image_id = first["successful"][0]["image_id"]
    record = client.get(f"/api/v1/images/{image_id}").json()
    managed = Path(test_settings.resolved_data_dir) / record["managed_path"]
    assert managed.read_bytes() == original_bytes

    if damage == "missing":
        managed.unlink()
    elif damage == "truncated":
        managed.write_bytes(original_bytes[:-1])
    else:
        # A byte-count-only verification must not accept a changed original.
        managed.write_bytes(bytes([original_bytes[0] ^ 1]) + original_bytes[1:])

    reupload = import_one(
        client,
        project["id"],
        filename="CANON_DUPLICATE.JPEG",
        content=original_bytes,
    )
    assert reupload["successful"] == [], reupload
    assert reupload["duplicates"] == [], reupload
    assert len(reupload["failed"]) == 1, reupload
    assert "missing or damaged" in reupload["failed"][0]["detail"]
    assert client.get(f"/api/v1/projects/{project['id']}/images").json()["total"] == 1
    if damage == "missing":
        assert not managed.exists()
    else:
        assert managed.read_bytes() != original_bytes


def test_camera_duplicate_of_verified_original_remains_a_duplicate(
    client: TestClient,
) -> None:
    """Verification does not block legitimate byte-identical JPG/JPEG aliases."""
    project = create_project(client, "Valid duplicate camera exposure")
    original = image_bytes("JPEG", size=(54, 40))
    first = import_one(client, project["id"], filename="DSC_001.JPG", content=original)
    reupload = import_one(client, project["id"], filename="DSC_001.JPEG", content=original)
    assert reupload["failed"] == [], reupload
    assert reupload["successful"] == [], reupload
    assert reupload["duplicates"][0]["duplicate_image_id"] == (first["successful"][0]["image_id"])


@pytest.mark.parametrize("damage", ["shorter", "larger"])
def test_camera_duplicate_skips_reading_invalid_size_original(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    damage: str,
) -> None:
    """A corrupted camera original with the wrong length must not need a full rehash."""
    project = create_project(client, "Removable camera duplicate short-circuit")
    source = image_bytes("JPEG", size=(55, 41))
    first = import_one(client, project["id"], filename="SONY_CARD_0103.JPG", content=source)
    image_id = first["successful"][0]["image_id"]
    record = client.get(f"/api/v1/images/{image_id}").json()
    managed = Path(test_settings.resolved_data_dir) / record["managed_path"]
    managed.write_bytes(source[:-7] if damage == "shorter" else source + b"corrupt")

    original_open = Path.open

    def reject_damaged_original_read(path: Path, mode: str = "r") -> BinaryIO:
        if path == managed and mode == "rb":
            raise AssertionError("Wrong-size original should not be read or hashed")
        return original_open(path, mode)

    monkeypatch.setattr(Path, "open", reject_damaged_original_read)
    reupload = import_one(client, project["id"], filename="CANON_RESEND.JPEG", content=source)

    assert reupload["successful"] == [], reupload
    assert reupload["duplicates"] == [], reupload
    assert len(reupload["failed"]) == 1, reupload
    assert "missing or damaged managed original" in reupload["failed"][0]["detail"]
    assert client.get(f"/api/v1/projects/{project['id']}/images").json()["total"] == 1


def test_transient_camera_original_read_denial_preserves_recoverable_duplicate(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Windows read denial must not discard a good resend or alter the original."""
    project = create_project(client, "Transient managed camera read denial")
    source = image_bytes("JPEG", size=(57, 43))
    first = import_one(client, project["id"], filename="SONY_ORIGINAL.JPG", content=source)
    image_id = first["successful"][0]["image_id"]
    record = client.get(f"/api/v1/images/{image_id}").json()
    managed = Path(test_settings.resolved_data_dir) / record["managed_path"]
    original_open = Path.open

    def reject_camera_read(path: Path, mode: str = "r") -> BinaryIO:
        if path == managed and mode == "rb":
            raise PermissionError("Simulated temporary Windows camera original read denial")
        return original_open(path, mode)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", reject_camera_read)
        denied = import_one(client, project["id"], filename="CANON_RESEND.JPEG", content=source)

    assert denied["successful"] == [], denied
    assert denied["duplicates"] == [], denied
    assert len(denied["failed"]) == 1, denied
    assert "missing or damaged managed original" in denied["failed"][0]["detail"]
    assert managed.read_bytes() == source
    assert client.get(f"/api/v1/projects/{project['id']}/images").json()["total"] == 1

    # A transient read failure must be recoverable without re-importing or
    # replacing a valid immutable scientific camera original.
    retried = import_one(client, project["id"], filename="CANON_RESEND.JPEG", content=source)
    assert retried["failed"] == [], retried
    assert retried["successful"] == [], retried
    assert retried["duplicates"][0]["duplicate_image_id"] == image_id
    assert managed.read_bytes() == source


def test_corrupted_duplicate_does_not_block_another_camera_image_in_batch(
    client: TestClient,
    test_settings: Settings,
) -> None:
    """A damaged earlier original must not abort an independent camera import."""
    project = create_project(client, "Mixed camera batch after damaged duplicate")
    original = image_bytes("JPEG", size=(61, 45))
    new_exposure = image_bytes("JPEG", size=(62, 46))
    first = import_one(client, project["id"], filename="SONY_OLD.JPG", content=original)
    original_id = first["successful"][0]["image_id"]
    record = client.get(f"/api/v1/images/{original_id}").json()
    managed = Path(test_settings.resolved_data_dir) / record["managed_path"]
    tampered = bytes([original[0] ^ 1]) + original[1:]
    managed.write_bytes(tampered)

    response = client.post(
        f"/api/v1/projects/{project['id']}/imports/images",
        files=[
            ("files", ("SONY_OLD_RESEND.JPEG", original, "image/jpeg")),
            ("files", ("CANON_NEW.JPG", new_exposure, "image/jpeg")),
        ],
        data={"relative_paths": ["camera/old.jpeg", "camera/new.jpg"]},
    )

    assert response.status_code == 200, response.text
    report = response.json()
    assert [item["filename"] for item in report["failed"]] == ["SONY_OLD_RESEND.JPEG"]
    assert "missing or damaged managed original" in report["failed"][0]["detail"]
    assert report["duplicates"] == []
    assert [item["filename"] for item in report["successful"]] == ["CANON_NEW.JPG"]
    new_id = report["successful"][0]["image_id"]
    assert client.get(f"/api/v1/images/{new_id}/content").content == new_exposure
    assert client.get(f"/api/v1/projects/{project['id']}/images").json()["total"] == 2
    assert managed.read_bytes() == tampered
