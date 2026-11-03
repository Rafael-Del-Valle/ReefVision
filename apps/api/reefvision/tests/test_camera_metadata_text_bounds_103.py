"""Bound untrusted camera text without fabricating scientific provenance."""

from __future__ import annotations

import pytest

from reefvision.storage.images import _json_safe


@pytest.mark.parametrize("length", [0, 1, 65_535, 65_536])
def test_camera_text_within_metadata_limit_is_preserved_exactly(length: int) -> None:
    value = "x" * length
    assert _json_safe(value) == value


def test_oversized_vendor_text_is_unknown_not_truncated() -> None:
    value = "vendor:" + ("x" * 65_536)
    assert _json_safe(value) is None


def test_oversized_nested_camera_text_does_not_discard_valid_measurements() -> None:
    metadata = {
        "manufacturer": "Canon",
        "vendor_blob": "x" * 65_537,
        "exposure": {"numerator": 1, "denominator": 200},
    }
    assert _json_safe(metadata) == {
        "manufacturer": "Canon",
        "vendor_blob": None,
        "exposure": {"numerator": 1, "denominator": 200},
    }
    # The metadata sanitizer is read-only.
    assert len(metadata["vendor_blob"]) == 65_537
