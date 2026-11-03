"""Regression coverage for untrusted camera metadata wrappers."""

from __future__ import annotations

from reefvision.storage.images import _json_safe


class UnprintableCameraValue:
    def __str__(self) -> str:
        raise RuntimeError("corrupt camera metadata wrapper")


def test_unprintable_exif_wrapper_is_unknown_not_an_import_failure() -> None:
    assert _json_safe(UnprintableCameraValue()) is None


def test_unprintable_nested_metadata_preserves_valid_measurements() -> None:
    result = _json_safe({"exposure": 0.004, "vendor": UnprintableCameraValue()})
    assert result == {"exposure": 0.004, "vendor": None}
