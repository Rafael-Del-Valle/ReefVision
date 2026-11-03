"""Regression coverage for bounded, untrusted camera metadata wrappers."""

from reefvision.storage.images import _json_safe


class VendorText:
    def __init__(self, text: str) -> None:
        self.text = text

    def __str__(self) -> str:
        return self.text


def test_vendor_wrapper_text_at_limit_is_preserved() -> None:
    text = "x" * 65_536
    assert _json_safe(VendorText(text)) == text


def test_vendor_wrapper_text_above_limit_is_unknown() -> None:
    assert _json_safe(VendorText("x" * 65_537)) is None


def test_vendor_dictionary_key_above_limit_is_discarded() -> None:
    assert _json_safe({VendorText("x" * 65_537): 10, "ISO": 200}) == {"ISO": 200}


def test_vendor_dictionary_key_at_limit_is_preserved() -> None:
    key = "k" * 65_536
    assert _json_safe({VendorText(key): 10}) == {key: 10}
