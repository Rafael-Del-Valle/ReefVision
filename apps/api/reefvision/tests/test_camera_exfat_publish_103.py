"""Regression tests for immutable original publication on filesystems without hard links.

The Windows/exFAT fallback must never overwrite an existing scientific original
or leave a partially copied original after a failed transfer.
"""

from __future__ import annotations

import errno
from pathlib import Path

import pytest

from reefvision.domain.errors import ValidationError
from reefvision.storage import images


def _deny_hard_link(*_args: object, **_kwargs: object) -> None:
    raise OSError(errno.EOPNOTSUPP, "hard links unsupported")


def test_exfat_fallback_preserves_bytes_and_removes_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged = tmp_path / "staging" / "camera.jpg"
    staged.parent.mkdir()
    payload = b"immutable camera original" * 100
    staged.write_bytes(payload)
    destination = tmp_path / "originals" / "camera.jpg"
    monkeypatch.setattr(images.os, "link", _deny_hard_link)

    images.commit_staged_image(staged, destination)

    assert destination.read_bytes() == payload
    assert not staged.exists()


def test_exfat_fallback_collision_does_not_overwrite_or_remove_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged = tmp_path / "staged.jpg"
    staged.write_bytes(b"new camera pixels")
    destination = tmp_path / "original.jpg"
    destination.write_bytes(b"existing scientific original")
    monkeypatch.setattr(images.os, "link", _deny_hard_link)

    with pytest.raises(ValidationError, match="already exists"):
        images.commit_staged_image(staged, destination)

    assert destination.read_bytes() == b"existing scientific original"
    assert staged.read_bytes() == b"new camera pixels"


def test_exfat_fallback_failed_copy_removes_only_incomplete_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged = tmp_path / "staged.jpg"
    staged.write_bytes(b"original bytes remain intact")
    destination = tmp_path / "originals" / "original.jpg"
    monkeypatch.setattr(images.os, "link", _deny_hard_link)

    def interrupted_copy(source: object, output: object, *, length: int) -> None:
        output.write(b"partial")
        raise OSError("disk disconnected during copy")

    monkeypatch.setattr(images.shutil, "copyfileobj", interrupted_copy)

    with pytest.raises(OSError, match="disk disconnected"):
        images.commit_staged_image(staged, destination)

    assert not destination.exists()
    assert staged.read_bytes() == b"original bytes remain intact"
