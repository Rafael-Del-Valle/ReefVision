"""Camera-style JPEG metadata must survive inspection without changing the source.

Synthetic fixtures exercise standard EXIF orientation and embedded ICC bytes.
They do not substitute for physical Canon/Sony camera acceptance.
"""

from __future__ import annotations

import hashlib

import pytest
from PIL import Image

from reefvision.storage.images import inspect_staged_image


@pytest.mark.parametrize(
    ("orientation", "suffix"),
    [
        (1, ".JPG"),
        (2, ".jpeg"),
        (3, ".JPEG"),
        (4, ".JFIF"),
        (5, ".JPE"),
        (6, ".JIF"),
        (7, ".JFI"),
        (8, ".JPG"),
        (0, ".JPG"),
        (9, ".JPG"),
    ],
)
def test_camera_jpeg_exif_orientation_and_icc_are_read_only(
    tmp_path, orientation: int, suffix: str
) -> None:
    path = tmp_path / f"camera_orientation_{orientation}{suffix}"
    exif = Image.Exif()
    exif[271] = "Synthetic Camera"
    exif[274] = orientation
    # A synthetic profile payload exercises metadata handling; it is not a
    # colorimetrically valid ICC profile and must not be used for color QC.
    icc_payload = b"synthetic-icc-fixture-" + bytes(range(32))
    Image.new("RGB", (23, 13), (12, 45, 90)).save(
        path, format="JPEG", exif=exif, icc_profile=icc_payload
    )
    original = path.read_bytes()
    digest = hashlib.sha256(original).hexdigest()

    inspected = inspect_staged_image(path, digest, len(original))

    assert inspected.sha256 == digest
    assert inspected.file_size_bytes == len(original)
    # EXIF orientation is advisory; never silently rotate the scientific
    # pixel coordinate system or change dimensions during import inspection.
    assert (inspected.width_px, inspected.height_px) == (23, 13)
    assert inspected.extension == ".jpg"
    assert inspected.media_type == "image/jpeg"
    assert inspected.metadata["exif"]["Orientation"] == orientation
    assert inspected.metadata["exif"]["Make"] == "Synthetic Camera"
    assert inspected.metadata["embedded_icc_profile_sha256"] == hashlib.sha256(
        icc_payload
    ).hexdigest()
    if orientation == 1:
        assert "exif_orientation_qc" not in inspected.metadata
        assert "exif_orientation_warning" not in inspected.metadata
    elif 2 <= orientation <= 8:
        assert inspected.metadata["exif_orientation_qc"] == "display-transformation-not-validated"
        assert "before spatial measurement" in inspected.metadata["exif_orientation_warning"]
    else:
        assert inspected.metadata["exif_orientation_qc"] == "invalid-or-unrecognized"
        assert (
            "displayed orientation is uncertain" in inspected.metadata["exif_orientation_warning"]
        )
    assert path.read_bytes() == original


def test_camera_without_orientation_does_not_invent_orientation_qc(tmp_path) -> None:
    path = tmp_path / "no_orientation.JPEG"
    Image.new("RGB", (17, 11), (12, 23, 34)).save(path, format="JPEG")
    original = path.read_bytes()
    inspected = inspect_staged_image(path, hashlib.sha256(original).hexdigest(), len(original))

    assert "exif_orientation_qc" not in inspected.metadata
    assert "exif_orientation_warning" not in inspected.metadata
    assert (inspected.width_px, inspected.height_px) == (17, 11)
    assert path.read_bytes() == original
