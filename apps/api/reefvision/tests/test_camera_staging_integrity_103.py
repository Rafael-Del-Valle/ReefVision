"""Regression coverage for immutable camera-image upload staging.

Scientific originals must never be overwritten or partially retained after a
failed upload. In particular, an exclusive-create collision belongs to another
upload and must not be unlinked by the unsuccessful writer.
"""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

import pytest

from reefvision.storage.images import stream_to_staging


class FailingCameraStream:
    def __init__(self) -> None:
        self.calls = 0

    def read(self, size: int = -1) -> bytes:
        self.calls += 1
        if self.calls == 1:
            return b"partial camera pixels"
        raise OSError("camera stream disconnected")


def test_camera_staging_preserves_exact_bytes_and_checksum(tmp_path: Path) -> None:
    payload = b"\xff\xd8\xff" + bytes(range(256)) * 9 + b"\xff\xd9"
    destination = tmp_path / "staging" / "original.jpg"

    checksum, size = stream_to_staging(BytesIO(payload), destination)

    assert destination.read_bytes() == payload
    assert checksum == hashlib.sha256(payload).hexdigest()
    assert size == len(payload)


def test_camera_staging_collision_does_not_delete_existing_original(tmp_path: Path) -> None:
    destination = tmp_path / "original.jpg"
    original = b"immutable existing scientific image"
    destination.write_bytes(original)

    with pytest.raises(FileExistsError):
        stream_to_staging(BytesIO(b"replacement"), destination)

    assert destination.read_bytes() == original


def test_camera_staging_stream_failure_removes_only_partial_new_file(tmp_path: Path) -> None:
    destination = tmp_path / "staging" / "failed.jpg"

    with pytest.raises(OSError, match="camera stream disconnected"):
        stream_to_staging(FailingCameraStream(), destination)

    assert not destination.exists()
    assert destination.parent.is_dir()
