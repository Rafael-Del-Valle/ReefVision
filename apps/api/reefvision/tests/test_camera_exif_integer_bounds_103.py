"""Oversized vendor EXIF integers cannot break strict JSON import responses."""

from __future__ import annotations

import json

from reefvision.storage.images import _json_safe


def test_oversized_camera_integer_is_unknown_not_json_failure() -> None:
    huge = 1 << 20_000
    metadata = {"camera_counter": huge, "exposure_us": 1200}
    safe = _json_safe(metadata)
    assert safe == {"camera_counter": None, "exposure_us": 1200}
    assert json.loads(json.dumps(safe, allow_nan=False)) == safe


def test_normal_large_camera_integer_remains_exact() -> None:
    valid = (1 << 512) + 7
    assert _json_safe(valid) == valid
    assert json.loads(json.dumps(_json_safe(valid), allow_nan=False)) == valid
