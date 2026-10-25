"""Prevent failed imports from deleting an existing scientific image original."""

from __future__ import annotations

import errno
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

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
