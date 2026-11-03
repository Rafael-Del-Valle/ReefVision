"""Camera EXIF wrappers must be inspected once, not twice per import."""

from __future__ import annotations

import hashlib

from PIL import Image

from reefvision.storage.images import inspect_staged_image


class StatefulExifValue:
    def __init__(self) -> None:
        self.calls = 0

    def __str__(self) -> str:
        self.calls += 1
        if self.calls > 1:
            raise RuntimeError("camera wrapper is not repeatable")
        return "vendor-value"


class CameraExif:
    def __init__(self, value: StatefulExifValue) -> None:
        self.value = value

    def __iter__(self):
        return iter({65000: self.value})

    def __getitem__(self, key: int):
        return {65000: self.value}[key]

    def keys(self):
        return [65000]

    def get_ifd(self, _ifd):
        return {}


def test_camera_exif_value_converted_once(tmp_path, monkeypatch) -> None:
    path = tmp_path / "camera.jpg"
    Image.new("RGB", (8, 8), (15, 30, 45)).save(path, "JPEG")
    original = path.read_bytes()
    wrapper = StatefulExifValue()
    monkeypatch.setattr(Image.Image, "getexif", lambda self: CameraExif(wrapper))

    result = inspect_staged_image(path, hashlib.sha256(original).hexdigest(), len(original))

    assert wrapper.calls == 1
    assert result.metadata["exif"]["65000"] == "vendor-value"
    assert path.read_bytes() == original
