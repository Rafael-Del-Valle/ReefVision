"""Regression: malformed vendor EXIF keys cannot reject valid camera pixels."""

import hashlib

from PIL import Image

from reefvision.storage.images import inspect_staged_image


class _BrokenTag:
    def __hash__(self):
        return 1234567

    def __eq__(self, other):
        return self is other

    def __str__(self):
        raise RuntimeError("vendor EXIF tag cannot be formatted")


class _CameraExif(dict):
    def get_ifd(self, _ifd):
        return {}


def test_unstringifiable_exif_tag_does_not_reject_jpeg(tmp_path, monkeypatch):
    path = tmp_path / "camera.jpg"
    Image.new("RGB", (8, 6), (20, 40, 60)).save(path, "JPEG")
    original = path.read_bytes()
    exif = _CameraExif({_BrokenTag(): "untrusted", 271: "Camera vendor"})
    monkeypatch.setattr(Image.Image, "getexif", lambda self: exif)

    inspected = inspect_staged_image(
        path, hashlib.sha256(original).hexdigest(), len(original)
    )

    assert inspected.width_px == 8
    assert inspected.height_px == 6
    assert inspected.metadata["exif"]["Make"] == "Camera vendor"
    assert len(inspected.metadata["exif"]) == 1
    assert path.read_bytes() == original
