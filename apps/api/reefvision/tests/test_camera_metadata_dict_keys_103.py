"""Regression: malformed vendor EXIF dictionary keys must not abort image import."""

from reefvision.storage.images import _json_safe


class UnstringifiableKey:
    def __hash__(self):
        return 42

    def __str__(self):
        raise ValueError("broken vendor key")


def test_nested_camera_metadata_skips_unstringifiable_keys():
    source = {UnstringifiableKey(): "untrusted", "exposure": 0.005}
    assert _json_safe(source) == {"exposure": 0.005}


def test_nested_camera_metadata_preserves_repeated_noncyclic_values():
    shared = {"ISO": 400}
    assert _json_safe([shared, shared]) == [{"ISO": 400}, {"ISO": 400}]
