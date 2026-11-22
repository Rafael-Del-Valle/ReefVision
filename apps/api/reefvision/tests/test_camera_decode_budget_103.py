"""Fail closed on Pillow warning-range camera images before loading huge pixel grids.

The production import budget is Pillow's current MAX_IMAGE_PIXELS; tests
lower it to exercise the boundary with tiny synthetic JPEG files. This does
not replace physical Sony/Canon camera or installed WebView2 acceptance.
"""

from __future__ import annotations

import hashlib
import warnings

import pytest
from PIL import Image

from reefvision.storage.images import (
    InvalidImageError,
    ensure_supported_extension,
    inspect_staged_image,
)


@pytest.mark.parametrize(
    ("width", "height", "allowed"),
    [(10, 10, True), (11, 10, False)],
)
def test_camera_jpeg_decode_budget_includes_boundary_but_rejects_warning_range(
    tmp_path, monkeypatch: pytest.MonkeyPatch, width: int, height: int, allowed: bool
) -> None:
    """Pillow's warning range must not bypass scientific import memory QC."""
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    source = tmp_path / f"DSC_{width}x{height}.JPG"
    Image.new("RGB", (width, height), (24, 90, 180)).save(source, format="JPEG")
    original = source.read_bytes()
    digest = hashlib.sha256(original).hexdigest()

    # Pillow warns at 101..200 pixels under this simulated decode budget.
    # The application must reject those images, not merely log the warning
    # and proceed to allocate a potentially unbounded decoded pixel array.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", Image.DecompressionBombWarning)
        if allowed:
            inspected = inspect_staged_image(source, digest, len(original))
            assert (inspected.width_px, inspected.height_px) == (width, height)
            assert inspected.sha256 == digest
            assert inspected.media_type == "image/jpeg"
        else:
            with pytest.raises(InvalidImageError, match="safe decode limit"):
                inspect_staged_image(source, digest, len(original))

    assert source.read_bytes() == original
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest


def test_camera_decode_budget_respects_explicit_pillow_disable(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An operator-approved Pillow policy can deliberately disable the limit."""
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", None)
    source = tmp_path / "research_panorama.jpeg"
    Image.new("RGB", (11, 10), (40, 75, 130)).save(source, format="JPEG")
    original = source.read_bytes()

    inspected = inspect_staged_image(source, hashlib.sha256(original).hexdigest(), len(original))
    assert inspected.width_px == 11
    assert inspected.height_px == 10
    assert inspected.sha256 == hashlib.sha256(original).hexdigest()
    assert source.read_bytes() == original


@pytest.mark.parametrize(
    "extension",
    [
        ".jpg",
        ".JPG",
        ".jpeg",
        ".JPEG",
        ".jpe",
        ".JPE",
        ".jfif",
        ".JFIF",
        ".jfi",
        ".JFI",
        ".jif",
        ".JIF",
    ],
)
def test_camera_jpeg_aliases_preserve_original_and_canonical_format(
    tmp_path, extension: str
) -> None:
    """Common camera JPEG aliases must share one verified scientific pixel frame."""
    source = tmp_path / f"DSC_0442{extension}"
    Image.new("RGB", (17, 13), (24, 90, 180)).save(source, format="JPEG")
    original = source.read_bytes()
    digest = hashlib.sha256(original).hexdigest()

    ensure_supported_extension(source.name)
    inspected = inspect_staged_image(source, digest, len(original))

    assert (inspected.width_px, inspected.height_px) == (17, 13)
    assert inspected.media_type == "image/jpeg"
    assert inspected.extension == ".jpg"
    assert inspected.sha256 == digest
    assert inspected.file_size_bytes == len(original)
    assert source.read_bytes() == original
