"""Camera metadata keys can alias after JSON-safe string conversion.

An import must not silently replace an earlier vendor measurement with a
later value under the same normalized key. Original image bytes are unaffected.
"""

from reefvision.storage.images import _json_safe


def test_numeric_and_text_vendor_keys_do_not_overwrite_first_value() -> None:
    metadata = {1: {"exposure": 0.25}, "1": {"exposure": 99}}
    assert _json_safe(metadata) == {"1": {"exposure": 0.25}}


def test_first_value_is_preserved_in_reverse_key_order() -> None:
    metadata = {"1": "original", 1: "alias"}
    assert _json_safe(metadata) == {"1": "original"}


def test_noncolliding_camera_metadata_is_preserved() -> None:
    metadata = {1: 0.25, "ISO": 400, "nested": {2: "lens", "2": "alias"}}
    assert _json_safe(metadata) == {
        "1": 0.25,
        "ISO": 400,
        "nested": {"2": "lens"},
    }
