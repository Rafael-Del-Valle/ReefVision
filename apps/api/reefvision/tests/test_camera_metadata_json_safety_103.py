"""Regression coverage for hostile camera metadata JSON conversion (1.0.3)."""

import math

from reefvision.storage.images import _json_safe


def test_recursive_camera_metadata_does_not_crash_import_serialization() -> None:
    cyclic: list[object] = []
    cyclic.append(cyclic)
    metadata = {"camera": cyclic, "exposure": 0.125, "invalid": math.inf}
    assert _json_safe(metadata) == {
        "camera": [None],
        "exposure": 0.125,
        "invalid": None,
    }


def test_shared_noncyclic_metadata_is_preserved() -> None:
    shared = {"iso": 250}
    assert _json_safe([shared, shared]) == [{"iso": 250}, {"iso": 250}]


def test_extremely_deep_camera_metadata_is_bounded() -> None:
    nested: object = "untrusted"
    for _ in range(100):
        nested = [nested]
    converted = _json_safe(nested)
    for _ in range(32):
        assert isinstance(converted, list)
        converted = converted[0]
    assert converted is None


def test_nonfinite_nested_camera_measurements_are_unknown() -> None:
    assert _json_safe({"samples": (1.0, math.nan, -math.inf)}) == {"samples": [1.0, None, None]}
