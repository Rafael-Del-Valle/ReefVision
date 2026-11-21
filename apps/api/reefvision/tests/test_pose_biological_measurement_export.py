from __future__ import annotations

from reefvision.services.pose_biological_measurement import canonical_package_hash


def test_export_hash_is_order_independent() -> None:
    assert canonical_package_hash({"b": 2, "a": 1}) == canonical_package_hash({"a": 1, "b": 2})
