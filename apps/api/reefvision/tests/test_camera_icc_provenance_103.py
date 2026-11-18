"""Camera JPEG ICC provenance is fingerprinted without treating color as calibrated.

The original capture bytes and pixel frame remain immutable. ICC payload
hashes are identifiers, never proof of valid or scientifically calibrated color.
"""

from __future__ import annotations

import hashlib

import pytest
from PIL import Image

from reefvision.storage.images import inspect_staged_image


@pytest.mark.parametrize(
    ("suffix", "mode"),
    [
        (".JPG", "RGB"),
        (".jpeg", "CMYK"),
        (".JFIF", "RGB"),
    ],
)
def test_camera_icc_profile_fingerprint_does_not_modify_original(
    tmp_path, suffix: str, mode: str
) -> None:
    path = tmp_path / ("camera_color" + suffix)
    # This deliberately opaque payload tests byte fidelity, not ICC validity.
    icc_payload = b"reefvision-test-icc-payload\x00binary\xff-not-calibration"
    color = (30, 75, 125, 10) if mode == "CMYK" else (30, 75, 125)
    Image.new(mode, (31, 17), color).save(path, format="JPEG", icc_profile=icc_payload)
    original = path.read_bytes()
    digest = hashlib.sha256(original).hexdigest()

    inspected = inspect_staged_image(path, digest, len(original))

    assert inspected.sha256 == digest
    assert inspected.extension == ".jpg"
    assert inspected.media_type == "image/jpeg"
    assert (inspected.width_px, inspected.height_px) == (31, 17)
    assert (
        inspected.metadata["embedded_icc_profile_sha256"] == hashlib.sha256(icc_payload).hexdigest()
    )
    assert inspected.metadata["embedded_icc_profile_size_bytes"] == len(icc_payload)
    assert inspected.metadata["embedded_icc_profile_validation"] == "not-validated"
    assert "icc_profile" not in inspected.metadata["info"]
    assert icc_payload.hex() not in str(inspected.metadata)
    with Image.open(path) as reopened:
        assert reopened.info["icc_profile"] == icc_payload
    assert path.read_bytes() == original


def test_camera_without_icc_does_not_invent_color_profile(tmp_path) -> None:
    path = tmp_path / "untagged_camera.JPEG"
    Image.new("RGB", (19, 13), (12, 35, 90)).save(path, format="JPEG")
    original = path.read_bytes()

    inspected = inspect_staged_image(path, hashlib.sha256(original).hexdigest(), len(original))

    assert "embedded_icc_profile_sha256" not in inspected.metadata
    assert "embedded_icc_profile_size_bytes" not in inspected.metadata
    assert "embedded_icc_profile_validation" not in inspected.metadata
    assert "embedded_icc_profile_warning" not in inspected.metadata
    assert path.read_bytes() == original
