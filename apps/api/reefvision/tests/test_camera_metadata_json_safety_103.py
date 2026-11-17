"""Regression coverage for hostile camera metadata JSON conversion (1.0.3)."""

import math

from reefvision.storage.images import (
    MAX_CAMERA_METADATA_CONTAINER_ITEMS,
    MAX_CAMERA_METADATA_TOTAL_NODES,
    _json_safe,
)


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


def test_oversized_vendor_metadata_list_does_not_expand_into_project_json() -> None:
    """Keep other measured tags while rejecting an unbounded vendor payload."""
    oversized = list(range(MAX_CAMERA_METADATA_CONTAINER_ITEMS + 1))
    assert _json_safe(oversized) is None
    assert _json_safe({"maker_data": oversized, "exposure_seconds": 0.125}) == {
        "maker_data": None,
        "exposure_seconds": 0.125,
    }


def test_oversized_vendor_metadata_mapping_does_not_expand_into_project_json() -> None:
    oversized = {str(index): index for index in range(MAX_CAMERA_METADATA_CONTAINER_ITEMS + 1)}
    assert _json_safe(oversized) is None
    # Legitimate, bounded camera arrays retain their original order and values.
    at_limit = list(range(MAX_CAMERA_METADATA_CONTAINER_ITEMS))
    assert _json_safe(at_limit) == at_limit


def test_aggregate_vendor_tree_budget_drops_entire_untrusted_value() -> None:
    """Bound a broad but individually valid tree without partial scientific metadata."""
    dense = [[0, 1, 2, 3] for _ in range(MAX_CAMERA_METADATA_CONTAINER_ITEMS)]
    assert len(dense) <= MAX_CAMERA_METADATA_CONTAINER_ITEMS
    assert sum(len(group) + 1 for group in dense) > MAX_CAMERA_METADATA_TOTAL_NODES
    assert _json_safe(dense) is None
    # A separate independently decoded exposure tag is still trustworthy.
    assert _json_safe({"exposure_seconds": 0.125}) == {"exposure_seconds": 0.125}


def test_bounded_nested_vendor_tree_retains_order_and_values() -> None:
    camera_channels = [[0, 1, 2, 3] for _ in range(100)]
    assert _json_safe(camera_channels) == camera_channels
