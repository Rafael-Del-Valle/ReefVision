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


def test_staged_jpeg_replacement_between_verification_and_decode_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A same-sized decodable JPEG swap must not publish stale capture provenance."""
    from PIL import Image

    from reefvision.storage import images

    staged = tmp_path / "capture.JPG"
    replacement = tmp_path / "replacement.JPG"
    Image.new("RGB", (23, 17), (25, 50, 75)).save(staged, format="JPEG")
    Image.new("RGB", (23, 17), (160, 20, 35)).save(replacement, format="JPEG")
    original = staged.read_bytes()
    changed = replacement.read_bytes()
    # Trailing JPEG data does not affect decoded pixels; normalize length
    # to demonstrate that st_size alone cannot detect the replacement.
    same_size = max(len(original), len(changed))
    original = original.ljust(same_size, b"\x00")
    changed = changed.ljust(same_size, b"\x00")
    staged.write_bytes(original)
    assert len(original) == len(changed)
    assert original != changed

    upload_hash = hashlib.sha256(original).hexdigest()
    original_open = images.Image.open
    opens = 0

    def swapped_open(*args: object, **kwargs: object):
        nonlocal opens
        opens += 1
        if opens == 2:
            staged.write_bytes(changed)
        return original_open(*args, **kwargs)

    monkeypatch.setattr(images.Image, "open", swapped_open)
    with pytest.raises(images.InvalidImageError, match="checksum or byte count mismatch"):
        images.inspect_staged_image(staged, upload_hash, len(original))

    assert opens == 2
    assert staged.read_bytes() == changed


def test_staged_camera_import_rejects_stale_file_size(tmp_path: Path) -> None:
    """A stale upload byte count cannot be stored with valid decoded pixels."""
    from PIL import Image

    from reefvision.storage.images import InvalidImageError, inspect_staged_image

    staged = tmp_path / "capture.jpeg"
    Image.new("RGB", (19, 11), (20, 40, 60)).save(staged, format="JPEG")
    original = staged.read_bytes()
    with pytest.raises(InvalidImageError, match="checksum or byte count mismatch"):
        inspect_staged_image(staged, hashlib.sha256(original).hexdigest(), len(original) + 1)
    assert staged.read_bytes() == original
