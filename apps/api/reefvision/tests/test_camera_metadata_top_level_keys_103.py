"""Regression tests for bounded EXIF and camera image-info keys."""

from reefvision.storage.images import _safe_metadata_key


class VendorKey:
    def __init__(self, text: str) -> None:
        self.text = text

    def __str__(self) -> str:
        return self.text


class BrokenVendorKey:
    def __str__(self) -> str:
        raise ValueError("invalid vendor tag")


def test_regular_camera_key_is_preserved() -> None:
    assert _safe_metadata_key("Make") == "Make"
    assert _safe_metadata_key(271) == "271"


def test_camera_key_at_boundary_is_preserved() -> None:
    value = "x" * 65_536
    assert _safe_metadata_key(VendorKey(value)) == value


def test_oversized_camera_key_is_discarded() -> None:
    assert _safe_metadata_key(VendorKey("x" * 65_537)) is None


def test_broken_vendor_key_is_discarded() -> None:
    assert _safe_metadata_key(BrokenVendorKey()) is None
